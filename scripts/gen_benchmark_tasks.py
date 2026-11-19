"""Generate 30 additional VEXA benchmark tasks (benchmarks/tasks/<id>/).

Each task: task.json, repo/ (starting code + visible tests), hidden_tests/, solution/.
Validity (checked by tests/test_evaluation.py::test_every_task_is_valid):
visible tests pass on repo, hidden tests fail on repo, solution passes both.
"""
import json
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
PYPROJECT = '[tool.pytest.ini_options]\npythonpath = ["."]\ntestpaths = ["tests"]\n'

DEADLINE = '''import threading


def _run_with_deadline(fn, seconds):
    """Run fn in a daemon thread; return (finished, value). Slow code fails fast instead of hanging."""
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("v", fn()), daemon=True)
    t.start()
    t.join(seconds)
    return (not t.is_alive()), box.get("v")
'''

TASKS = []


def task(id, title, category, difficulty, requirement, criteria, repo, visible, hidden, solution):
    TASKS.append(dict(id=id, title=title, category=category, difficulty=difficulty, requirement=requirement,
                      criteria=criteria, repo=repo, visible=visible, hidden=hidden, solution=solution))


# ============================================================== bug_fix
task("bugfix_mean_integer_division", "Fix mean() rounding and empty input", "bug_fix", "easy",
     "stats.mean(xs) truncates its result (mean([2, 3]) returns 2) and crashes with ZeroDivisionError on an\n"
     "empty list. It must return the exact float mean, and raise ValueError(\"mean of empty sequence\") for an empty list.",
     ["mean([2, 3]) == 2.5", "mean([1, 2, 3]) == 2", "mean([]) raises ValueError"],
     {"stats.py": "def mean(xs):\n    return sum(xs) // len(xs)\n"},
     {"test_stats.py": "from stats import mean\n\ndef test_whole():\n    assert mean([1, 2, 3]) == 2\n"},
     {"test_hidden_mean.py": "import pytest\nfrom stats import mean\n\ndef test_fraction():\n    assert mean([2, 3]) == 2.5\n    assert mean([1, 2]) == 1.5\n\n"
      "def test_empty():\n    with pytest.raises(ValueError):\n        mean([])\n"},
     {"stats.py": "def mean(xs):\n    if not xs:\n        raise ValueError(\"mean of empty sequence\")\n    return sum(xs) / len(xs)\n"})

task("bugfix_leap_year", "Fix leap-year rule for centuries", "bug_fix", "easy",
     "dates.is_leap(year) only checks divisibility by 4, so 1900 and 2100 are wrongly leap years.\n"
     "Apply the Gregorian rule: divisible by 4, except centuries, unless divisible by 400.",
     ["is_leap(2024) is True", "is_leap(1900) is False", "is_leap(2000) is True"],
     {"dates.py": "def is_leap(year):\n    return year % 4 == 0\n\n\ndef days_in_february(year):\n    return 29 if is_leap(year) else 28\n"},
     {"test_dates.py": "from dates import is_leap, days_in_february\n\ndef test_basic():\n    assert is_leap(2024) and not is_leap(2023)\n\n"
      "def test_feb():\n    assert days_in_february(2024) == 29\n"},
     {"test_hidden_leap.py": "from dates import is_leap, days_in_february\n\ndef test_centuries():\n    assert not is_leap(1900)\n    assert not is_leap(2100)\n    assert is_leap(2000)\n    assert is_leap(2400)\n\n"
      "def test_feb_century():\n    assert days_in_february(1900) == 28\n"},
     {"dates.py": "def is_leap(year):\n    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)\n\n\ndef days_in_february(year):\n    return 29 if is_leap(year) else 28\n"})

task("bugfix_slugify", "Fix slugify for punctuation and spacing", "bug_fix", "easy",
     "text.slugify(s) only lowercases and replaces single spaces with '-', so \"  Hello,  World! \" becomes\n"
     "\"--hello,--world!-\". It must produce lowercase ASCII letters and digits separated by single hyphens,\n"
     "with no leading or trailing hyphen.",
     ["slugify('Hello World') == 'hello-world'", "slugify('  Hello,  World! ') == 'hello-world'", "slugify('Python 3.12 rocks') == 'python-3-12-rocks'"],
     {"text.py": "def slugify(s):\n    return s.lower().replace(\" \", \"-\")\n"},
     {"test_text.py": "from text import slugify\n\ndef test_simple():\n    assert slugify('Hello World') == 'hello-world'\n"},
     {"test_hidden_slugify.py": "from text import slugify\n\ndef test_punctuation():\n    assert slugify('  Hello,  World! ') == 'hello-world'\n\n"
      "def test_digits():\n    assert slugify('Python 3.12 rocks') == 'python-3-12-rocks'\n\ndef test_only_symbols():\n    assert slugify('!!!') == ''\n"},
     {"text.py": "import re\n\n\ndef slugify(s):\n    return re.sub(r\"[^a-z0-9]+\", \"-\", s.lower()).strip(\"-\")\n"})

task("bugfix_roman_numerals", "Roman numerals: subtractive notation", "bug_fix", "medium",
     "roman.to_roman(n) writes 4 as 'IIII' and 9 as 'VIIII'. Use standard subtractive notation\n"
     "(IV, IX, XL, XC, CD, CM) for 1 <= n <= 3999, and raise ValueError outside that range.",
     ["to_roman(4) == 'IV'", "to_roman(1994) == 'MCMXCIV'", "to_roman(0) raises ValueError"],
     {"roman.py": "VALUES = [(1000, 'M'), (500, 'D'), (100, 'C'), (50, 'L'), (10, 'X'), (5, 'V'), (1, 'I')]\n\n\n"
      "def to_roman(n):\n    out = ''\n    for value, sym in VALUES:\n        while n >= value:\n            out += sym\n            n -= value\n    return out\n"},
     {"test_roman.py": "from roman import to_roman\n\ndef test_additive():\n    assert to_roman(3) == 'III'\n    assert to_roman(1666) == 'MDCLXVI'\n"},
     {"test_hidden_roman.py": "import pytest\nfrom roman import to_roman\n\ndef test_subtractive():\n    assert to_roman(4) == 'IV'\n    assert to_roman(9) == 'IX'\n    assert to_roman(40) == 'XL'\n"
      "    assert to_roman(1994) == 'MCMXCIV'\n    assert to_roman(3999) == 'MMMCMXCIX'\n\n"
      "@pytest.mark.parametrize('n', [0, -1, 4000])\ndef test_range(n):\n    with pytest.raises(ValueError):\n        to_roman(n)\n"},
     {"roman.py": "VALUES = [(1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'), (100, 'C'), (90, 'XC'),\n"
      "          (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]\n\n\n"
      "def to_roman(n):\n    if not 1 <= n <= 3999:\n        raise ValueError(f\"out of range: {n}\")\n    out = ''\n"
      "    for value, sym in VALUES:\n        while n >= value:\n            out += sym\n            n -= value\n    return out\n"})

task("bugfix_merge_intervals", "Merge unsorted and touching intervals", "bug_fix", "medium",
     "intervals.merge(intervals) assumes the input is sorted and does not merge intervals that only touch\n"
     "([1, 4] and [4, 5]). It must accept intervals in any order, merge overlapping or touching ones, return\n"
     "them sorted by start, and not modify the input list.",
     ["merge([[8,10],[1,3],[2,6]]) == [[1,6],[8,10]]", "merge([[1,4],[4,5]]) == [[1,5]]", "input not mutated"],
     {"intervals.py": "def merge(intervals):\n    out = []\n    for start, end in intervals:\n        if out and start < out[-1][1]:\n"
      "            out[-1][1] = max(out[-1][1], end)\n        else:\n            out.append([start, end])\n    return out\n"},
     {"test_intervals.py": "from intervals import merge\n\ndef test_sorted_overlap():\n    assert merge([[1, 3], [2, 6], [8, 10]]) == [[1, 6], [8, 10]]\n"},
     {"test_hidden_intervals.py": "from intervals import merge\n\ndef test_unsorted():\n    assert merge([[8, 10], [1, 3], [2, 6]]) == [[1, 6], [8, 10]]\n\n"
      "def test_touching():\n    assert merge([[1, 4], [4, 5]]) == [[1, 5]]\n\ndef test_no_mutation():\n    data = [[5, 6], [1, 2]]\n    merge(data)\n    assert data == [[5, 6], [1, 2]]\n\n"
      "def test_empty():\n    assert merge([]) == []\n"},
     {"intervals.py": "def merge(intervals):\n    out = []\n    for start, end in sorted(intervals):\n        if out and start <= out[-1][1]:\n"
      "            out[-1][1] = max(out[-1][1], end)\n        else:\n            out.append([start, end])\n    return out\n"})

# ============================================================== feature
task("feature_stack_peek", "Add peek, is_empty and len to Stack", "feature", "easy",
     "stack.Stack supports push and pop. Add peek() (return the top item without removing it), is_empty(),\n"
     "and len(stack). pop() and peek() on an empty stack must raise IndexError(\"empty stack\").",
     ["peek returns top without removing", "len(s) counts items", "pop/peek on empty raise IndexError('empty stack')"],
     {"stack.py": "class Stack:\n    def __init__(self):\n        self._items = []\n\n    def push(self, item):\n        self._items.append(item)\n\n"
      "    def pop(self):\n        return self._items.pop()\n"},
     {"test_stack.py": "from stack import Stack\n\ndef test_push_pop():\n    s = Stack()\n    s.push(1)\n    s.push(2)\n    assert s.pop() == 2\n"},
     {"test_hidden_stack.py": "import pytest\nfrom stack import Stack\n\ndef test_peek():\n    s = Stack()\n    s.push('a')\n    s.push('b')\n    assert s.peek() == 'b'\n    assert len(s) == 2\n\n"
      "def test_empty():\n    s = Stack()\n    assert s.is_empty() and len(s) == 0\n    with pytest.raises(IndexError, match='empty stack'):\n        s.pop()\n"
      "    with pytest.raises(IndexError, match='empty stack'):\n        s.peek()\n"},
     {"stack.py": "class Stack:\n    def __init__(self):\n        self._items = []\n\n    def push(self, item):\n        self._items.append(item)\n\n"
      "    def pop(self):\n        if not self._items:\n            raise IndexError(\"empty stack\")\n        return self._items.pop()\n\n"
      "    def peek(self):\n        if not self._items:\n            raise IndexError(\"empty stack\")\n        return self._items[-1]\n\n"
      "    def is_empty(self):\n        return not self._items\n\n    def __len__(self):\n        return len(self._items)\n"})

task("feature_kelvin_conversion", "Add Kelvin to temperature conversion", "feature", "easy",
     "temperature.convert(value, from_unit, to_unit) converts between 'C' and 'F'. Add 'K' (Kelvin) in both\n"
     "directions. Results are rounded to 2 decimals. Unknown units still raise ValueError, and a Kelvin\n"
     "input below 0 raises ValueError.",
     ["convert(0, 'C', 'K') == 273.15", "convert(212, 'F', 'K') == 373.15", "convert(-1, 'K', 'C') raises ValueError"],
     {"temperature.py": "def convert(value, from_unit, to_unit):\n    if from_unit == to_unit:\n        return round(value, 2)\n"
      "    if (from_unit, to_unit) == ('C', 'F'):\n        return round(value * 9 / 5 + 32, 2)\n    if (from_unit, to_unit) == ('F', 'C'):\n"
      "        return round((value - 32) * 5 / 9, 2)\n    raise ValueError(f\"unsupported conversion {from_unit}->{to_unit}\")\n"},
     {"test_temperature.py": "import pytest\nfrom temperature import convert\n\ndef test_c_f():\n    assert convert(100, 'C', 'F') == 212\n    assert convert(32, 'F', 'C') == 0\n\n"
      "def test_unknown():\n    with pytest.raises(ValueError):\n        convert(1, 'C', 'X')\n"},
     {"test_hidden_kelvin.py": "import pytest\nfrom temperature import convert\n\ndef test_to_k():\n    assert convert(0, 'C', 'K') == 273.15\n    assert convert(212, 'F', 'K') == 373.15\n\n"
      "def test_from_k():\n    assert convert(273.15, 'K', 'C') == 0\n    assert convert(0, 'K', 'F') == -459.67\n\n"
      "def test_negative_kelvin():\n    with pytest.raises(ValueError):\n        convert(-1, 'K', 'C')\n"},
     {"temperature.py": "TO_C = {'C': lambda v: v, 'F': lambda v: (v - 32) * 5 / 9, 'K': lambda v: v - 273.15}\n"
      "FROM_C = {'C': lambda c: c, 'F': lambda c: c * 9 / 5 + 32, 'K': lambda c: c + 273.15}\n\n\n"
      "def convert(value, from_unit, to_unit):\n    if from_unit not in TO_C or to_unit not in FROM_C:\n"
      "        raise ValueError(f\"unsupported conversion {from_unit}->{to_unit}\")\n    if from_unit == 'K' and value < 0:\n"
      "        raise ValueError(\"Kelvin cannot be negative\")\n    return round(FROM_C[to_unit](TO_C[from_unit](value)), 2)\n"})

task("feature_word_frequencies", "Word frequency counter", "feature", "easy",
     "textstats.py has char_count(text). Add word_frequencies(text) returning a dict of lowercase word -> count.\n"
     "Words are runs of letters, digits or apostrophes; punctuation is ignored.",
     ["word_frequencies('The cat. the CAT!') == {'the': 2, 'cat': 2}", "word_frequencies('') == {}", "apostrophes kept: \"don't\""],
     {"textstats.py": "def char_count(text):\n    return len(text)\n"},
     {"test_textstats.py": "from textstats import char_count\n\ndef test_chars():\n    assert char_count('abc') == 3\n"},
     {"test_hidden_words.py": "from textstats import word_frequencies\n\ndef test_counts():\n    assert word_frequencies('The cat. the CAT!') == {'the': 2, 'cat': 2}\n\n"
      "def test_empty():\n    assert word_frequencies('') == {}\n\ndef test_apostrophe():\n    assert word_frequencies(\"Don't stop, don't.\") == {\"don't\": 2, 'stop': 1}\n"},
     {"textstats.py": "import re\nfrom collections import Counter\n\n\ndef char_count(text):\n    return len(text)\n\n\n"
      "def word_frequencies(text):\n    return dict(Counter(re.findall(r\"[a-z0-9']+\", text.lower())))\n"})

task("feature_business_days", "Count business days between dates", "feature", "medium",
     "workdays.py has days_between(start, end). Add business_days(start, end, holidays=()) that counts\n"
     "Monday–Friday dates from start to end inclusive, excluding any date in holidays. If end is before\n"
     "start, return 0.",
     ["Mon..Fri of one week == 5", "a full two-week span == 10", "holidays excluded", "end < start -> 0"],
     {"workdays.py": "from datetime import date\n\n\ndef days_between(start: date, end: date) -> int:\n    return (end - start).days\n"},
     {"test_workdays.py": "from datetime import date\nfrom workdays import days_between\n\ndef test_days():\n    assert days_between(date(2024, 1, 1), date(2024, 1, 31)) == 30\n"},
     {"test_hidden_business.py": "from datetime import date\nfrom workdays import business_days\n\ndef test_week():\n    assert business_days(date(2024, 1, 1), date(2024, 1, 5)) == 5\n\n"
      "def test_two_weeks():\n    assert business_days(date(2024, 1, 1), date(2024, 1, 14)) == 10\n\ndef test_weekend_only():\n    assert business_days(date(2024, 1, 6), date(2024, 1, 7)) == 0\n\n"
      "def test_holidays():\n    assert business_days(date(2024, 1, 1), date(2024, 1, 5), holidays=[date(2024, 1, 1)]) == 4\n\n"
      "def test_reversed():\n    assert business_days(date(2024, 1, 5), date(2024, 1, 1)) == 0\n"},
     {"workdays.py": "from datetime import date, timedelta\n\n\ndef days_between(start: date, end: date) -> int:\n    return (end - start).days\n\n\n"
      "def business_days(start: date, end: date, holidays=()) -> int:\n    skip = set(holidays)\n    count = 0\n    d = start\n    while d <= end:\n"
      "        if d.weekday() < 5 and d not in skip:\n            count += 1\n        d += timedelta(days=1)\n    return count\n"})

task("feature_lru_eviction", "LRU eviction for the cache", "feature", "hard",
     "cache.Cache(capacity) stores values with put(key, value) and get(key, default=None) but never evicts.\n"
     "Make it a least-recently-used cache: when a put would exceed capacity, evict the least recently used\n"
     "key. Both get (on a hit) and put count as a use. len(cache) returns the number of stored keys.\n"
     "capacity < 1 raises ValueError.",
     ["capacity respected", "get refreshes recency", "updating a key refreshes it", "Cache(0) raises ValueError"],
     {"cache.py": "class Cache:\n    def __init__(self, capacity):\n        self.capacity = capacity\n        self._data = {}\n\n"
      "    def put(self, key, value):\n        self._data[key] = value\n\n    def get(self, key, default=None):\n        return self._data.get(key, default)\n\n"
      "    def __len__(self):\n        return len(self._data)\n"},
     {"test_cache.py": "from cache import Cache\n\ndef test_put_get():\n    c = Cache(2)\n    c.put('a', 1)\n    assert c.get('a') == 1\n    assert c.get('zz', 'd') == 'd'\n"},
     {"test_hidden_lru.py": "import pytest\nfrom cache import Cache\n\ndef test_evicts_lru():\n    c = Cache(2)\n    c.put('a', 1)\n    c.put('b', 2)\n    c.put('c', 3)\n"
      "    assert c.get('a') is None and c.get('b') == 2 and c.get('c') == 3\n    assert len(c) == 2\n\n"
      "def test_get_refreshes():\n    c = Cache(2)\n    c.put('a', 1)\n    c.put('b', 2)\n    c.get('a')\n    c.put('c', 3)\n    assert c.get('a') == 1 and c.get('b') is None\n\n"
      "def test_update_refreshes():\n    c = Cache(2)\n    c.put('a', 1)\n    c.put('b', 2)\n    c.put('a', 10)\n    c.put('c', 3)\n    assert c.get('a') == 10 and c.get('b') is None\n\n"
      "def test_bad_capacity():\n    with pytest.raises(ValueError):\n        Cache(0)\n"},
     {"cache.py": "from collections import OrderedDict\n\n\nclass Cache:\n    def __init__(self, capacity):\n        if capacity < 1:\n"
      "            raise ValueError(\"capacity must be >= 1\")\n        self.capacity = capacity\n        self._data = OrderedDict()\n\n"
      "    def put(self, key, value):\n        self._data[key] = value\n        self._data.move_to_end(key)\n        if len(self._data) > self.capacity:\n"
      "            self._data.popitem(last=False)\n\n    def get(self, key, default=None):\n        if key not in self._data:\n            return default\n"
      "        self._data.move_to_end(key)\n        return self._data[key]\n\n    def __len__(self):\n        return len(self._data)\n"})

# ============================================================== refactoring
task("refactor_tax_constant", "Extract the tax rate constant", "refactoring", "easy",
     "invoice.py hard-codes the 20% tax rate (0.2) in subtotal_with_tax, tax_amount and line_total.\n"
     "Introduce a module-level TAX_RATE = 0.2 and use it everywhere, so changing TAX_RATE changes all three.\n"
     "Behaviour with the default rate must not change.",
     ["invoice.TAX_RATE == 0.2", "all three functions read TAX_RATE", "results unchanged"],
     {"invoice.py": "def subtotal_with_tax(amount):\n    return round(amount * (1 + 0.2), 2)\n\n\ndef tax_amount(amount):\n    return round(amount * 0.2, 2)\n\n\n"
      "def line_total(qty, unit_price):\n    return round(qty * unit_price * 1.2, 2)\n"},
     {"test_invoice.py": "from invoice import subtotal_with_tax, tax_amount, line_total\n\ndef test_values():\n    assert subtotal_with_tax(100) == 120.0\n"
      "    assert tax_amount(50) == 10.0\n    assert line_total(3, 10) == 36.0\n"},
     {"test_hidden_tax.py": "import invoice\n\ndef test_constant():\n    assert invoice.TAX_RATE == 0.2\n\n"
      "def test_all_use_constant(monkeypatch):\n    monkeypatch.setattr(invoice, 'TAX_RATE', 0.1)\n    assert invoice.subtotal_with_tax(100) == 110.0\n"
      "    assert invoice.tax_amount(50) == 5.0\n    assert invoice.line_total(3, 10) == 33.0\n"},
     {"invoice.py": "TAX_RATE = 0.2\n\n\ndef subtotal_with_tax(amount):\n    return round(amount * (1 + TAX_RATE), 2)\n\n\n"
      "def tax_amount(amount):\n    return round(amount * TAX_RATE, 2)\n\n\ndef line_total(qty, unit_price):\n    return round(qty * unit_price * (1 + TAX_RATE), 2)\n"})

task("refactor_shape_dispatch", "Replace if/elif chain with a dispatch table", "refactoring", "medium",
     "shapes.area(shape) picks the formula with an if/elif chain on shape['kind']. Refactor it to look the\n"
     "formula up in a module-level dict AREA_FUNCS (kind -> function taking the shape dict), so new kinds can\n"
     "be registered without editing area(). Unknown kinds still raise ValueError. Results must not change.",
     ["AREA_FUNCS has circle, square, rectangle", "registering AREA_FUNCS['triangle'] makes area() support it", "unknown kind -> ValueError"],
     {"shapes.py": "import math\n\n\ndef area(shape):\n    kind = shape['kind']\n    if kind == 'circle':\n        return math.pi * shape['r'] ** 2\n"
      "    elif kind == 'square':\n        return shape['side'] ** 2\n    elif kind == 'rectangle':\n        return shape['w'] * shape['h']\n"
      "    else:\n        raise ValueError(f\"unknown shape {kind}\")\n"},
     {"test_shapes.py": "import math\nimport pytest\nfrom shapes import area\n\ndef test_areas():\n    assert area({'kind': 'square', 'side': 3}) == 9\n"
      "    assert area({'kind': 'rectangle', 'w': 2, 'h': 5}) == 10\n    assert area({'kind': 'circle', 'r': 1}) == pytest.approx(math.pi)\n\n"
      "def test_unknown():\n    with pytest.raises(ValueError):\n        area({'kind': 'hexagon'})\n"},
     {"test_hidden_dispatch.py": "import pytest\nimport shapes\n\ndef test_table():\n    assert {'circle', 'square', 'rectangle'} <= set(shapes.AREA_FUNCS)\n\n"
      "def test_register(monkeypatch):\n    monkeypatch.setitem(shapes.AREA_FUNCS, 'triangle', lambda s: s['b'] * s['h'] / 2)\n"
      "    assert shapes.area({'kind': 'triangle', 'b': 4, 'h': 3}) == 6\n\ndef test_unknown():\n    with pytest.raises(ValueError):\n        shapes.area({'kind': 'blob'})\n"},
     {"shapes.py": "import math\n\nAREA_FUNCS = {\n    'circle': lambda s: math.pi * s['r'] ** 2,\n    'square': lambda s: s['side'] ** 2,\n"
      "    'rectangle': lambda s: s['w'] * s['h'],\n}\n\n\ndef area(shape):\n    fn = AREA_FUNCS.get(shape['kind'])\n    if fn is None:\n"
      "        raise ValueError(f\"unknown shape {shape['kind']}\")\n    return fn(shape)\n"})

task("refactor_email_validation", "Deduplicate email validation", "refactoring", "easy",
     "accounts.register(user) and accounts.update_email(user, email) each contain the same inline email check.\n"
     "Extract validate_email(email) -> bool (true when there is exactly one '@' with a non-empty local part and\n"
     "a domain containing a '.') and call it from both. Behaviour must not change.",
     ["validate_email('a@b.co') is True", "validate_email('a@b') is False", "both callers use validate_email"],
     {"accounts.py": "def register(user):\n    email = user['email']\n    local, _, domain = email.partition('@')\n"
      "    if email.count('@') != 1 or not local or '.' not in domain:\n        raise ValueError('invalid email')\n    return {**user, 'active': True}\n\n\n"
      "def update_email(user, email):\n    local, _, domain = email.partition('@')\n    if email.count('@') != 1 or not local or '.' not in domain:\n"
      "        raise ValueError('invalid email')\n    return {**user, 'email': email}\n"},
     {"test_accounts.py": "import pytest\nfrom accounts import register, update_email\n\ndef test_register():\n    assert register({'email': 'a@b.co'})['active']\n"
      "    with pytest.raises(ValueError):\n        register({'email': 'nope'})\n\ndef test_update():\n    assert update_email({'email': 'a@b.co'}, 'c@d.io')['email'] == 'c@d.io'\n"},
     {"test_hidden_validate.py": "import inspect\nimport pytest\nimport accounts\n\ndef test_validate():\n    assert accounts.validate_email('a@b.co')\n"
      "    for bad in ['a@b', '@b.co', 'a@@b.co', 'ab.co']:\n        assert not accounts.validate_email(bad)\n\n"
      "def test_callers_reuse_it():\n    for fn in (accounts.register, accounts.update_email):\n        assert 'validate_email' in inspect.getsource(fn)\n\n"
      "def test_behaviour():\n    with pytest.raises(ValueError):\n        accounts.update_email({}, 'x@y')\n"},
     {"accounts.py": "def validate_email(email):\n    local, _, domain = email.partition('@')\n    return email.count('@') == 1 and bool(local) and '.' in domain\n\n\n"
      "def register(user):\n    if not validate_email(user['email']):\n        raise ValueError('invalid email')\n    return {**user, 'active': True}\n\n\n"
      "def update_email(user, email):\n    if not validate_email(email):\n        raise ValueError('invalid email')\n    return {**user, 'email': email}\n"})

# ============================================================== security
SQL_REPO = ("import sqlite3\n\n\ndef make_db():\n    conn = sqlite3.connect(':memory:')\n    conn.execute('CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT)')\n"
            "    conn.executemany('INSERT INTO products (name) VALUES (?)', [('apple',), ('apricot',), ('banana',), (\"Bob's widget\",)])\n    return conn\n\n\n")
task("security_sql_injection_search", "Fix SQL injection in product search", "security", "medium",
     "products.search(conn, term) builds its LIKE query with an f-string, so a term such as \"%' OR 1=1 --\"\n"
     "returns every row and a term with an apostrophe crashes. Use a parameterised query. Results are names\n"
     "containing term (case-insensitive), sorted alphabetically.",
     ["search(conn, 'ap') == ['apple', 'apricot']", "injection term returns []", "\"Bob's\" finds \"Bob's widget\""],
     {"products.py": SQL_REPO + "def search(conn, term):\n    rows = conn.execute(f\"SELECT name FROM products WHERE name LIKE '%{term}%' ORDER BY name\")\n"
      "    return [r[0] for r in rows]\n"},
     {"test_products.py": "from products import make_db, search\n\ndef test_search():\n    assert search(make_db(), 'ap') == ['apple', 'apricot']\n"},
     {"test_hidden_injection.py": "from products import make_db, search\n\ndef test_injection():\n    assert search(make_db(), \"%' OR 1=1 --\") == []\n\n"
      "def test_apostrophe():\n    assert search(make_db(), \"Bob's\") == [\"Bob's widget\"]\n\ndef test_case():\n    assert search(make_db(), 'BAN') == ['banana']\n"},
     {"products.py": SQL_REPO + "def search(conn, term):\n    rows = conn.execute(\"SELECT name FROM products WHERE name LIKE ? ORDER BY name\", (f\"%{term}%\",))\n"
      "    return [r[0] for r in rows]\n"})

task("security_password_hashing", "Hash stored passwords", "security", "medium",
     "auth.UserStore keeps passwords in plain text. Store a salted hash instead: hashlib.pbkdf2_hmac('sha256', ...)\n"
     "with at least 100_000 iterations and a random 16-byte salt per user (os.urandom). verify(username, password)\n"
     "must still work and return False for unknown users.",
     ["stored value never contains the password", "same password -> different stored values", "verify works; wrong password False"],
     {"auth.py": "class UserStore:\n    def __init__(self):\n        self._users = {}\n\n    def add(self, username, password):\n        self._users[username] = password\n\n"
      "    def stored(self, username):\n        return self._users[username]\n\n    def verify(self, username, password):\n        return self._users.get(username) == password\n"},
     {"test_auth.py": "from auth import UserStore\n\ndef test_verify():\n    s = UserStore()\n    s.add('ada', 'pw1')\n    assert s.verify('ada', 'pw1')\n    assert not s.verify('ada', 'nope')\n    assert not s.verify('bob', 'pw1')\n"},
     {"test_hidden_hashing.py": "from auth import UserStore\n\ndef _as_bytes(v):\n    return v if isinstance(v, bytes) else repr(v).encode()\n\n"
      "def test_not_plaintext():\n    s = UserStore()\n    s.add('ada', 'correct horse')\n    assert b'correct horse' not in _as_bytes(s.stored('ada'))\n\n"
      "def test_salted():\n    s = UserStore()\n    s.add('a', 'same')\n    s.add('b', 'same')\n    assert s.stored('a') != s.stored('b')\n\n"
      "def test_verify():\n    s = UserStore()\n    s.add('ada', 'pw1')\n    assert s.verify('ada', 'pw1') and not s.verify('ada', 'pw2') and not s.verify('x', 'pw1')\n"},
     {"auth.py": "import hashlib\nimport hmac\nimport os\n\nITERATIONS = 100_000\n\n\nclass UserStore:\n    def __init__(self):\n        self._users = {}\n\n"
      "    def add(self, username, password):\n        salt = os.urandom(16)\n        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)\n"
      "        self._users[username] = salt + digest\n\n    def stored(self, username):\n        return self._users[username]\n\n"
      "    def verify(self, username, password):\n        rec = self._users.get(username)\n        if rec is None:\n            return False\n        salt, digest = rec[:16], rec[16:]\n"
      "        return hmac.compare_digest(digest, hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS))\n"})

task("security_token_compare", "Constant-time token check", "security", "easy",
     "tokens.check_token(given, expected) compares with ==, which leaks timing and accepts two empty tokens.\n"
     "Use hmac.compare_digest, and return False when either token is None or empty.",
     ["check_token('abc', 'abc') is True", "check_token('', '') is False", "check_token(None, 'abc') is False", "uses hmac.compare_digest"],
     {"tokens.py": "def check_token(given, expected):\n    return given == expected\n"},
     {"test_tokens.py": "from tokens import check_token\n\ndef test_match():\n    assert check_token('abc', 'abc')\n    assert not check_token('abc', 'abd')\n"},
     {"test_hidden_tokens.py": "import inspect\nimport tokens\n\ndef test_empty():\n    assert not tokens.check_token('', '')\n    assert not tokens.check_token(None, 'abc')\n"
      "    assert not tokens.check_token('abc', None)\n    assert not tokens.check_token(None, None)\n\ndef test_constant_time():\n    assert 'compare_digest' in inspect.getsource(tokens.check_token)\n"},
     {"tokens.py": "import hmac\n\n\ndef check_token(given, expected):\n    if not given or not expected:\n        return False\n"
      "    return hmac.compare_digest(given.encode(), expected.encode())\n"})

# ============================================================== performance
task("performance_has_duplicates", "Linear-time duplicate check", "performance", "easy",
     "listutil.has_duplicates(items) compares every pair, so 200_000 items never finish. Make it run in linear\n"
     "time (well under a second for 200_000 hashable items) without changing results.",
     ["200_000 unique ints finish in < 1 s and return False", "[1, 2, 1] -> True", "[] -> False"],
     {"listutil.py": "def has_duplicates(items):\n    for i in range(len(items)):\n        for j in range(i + 1, len(items)):\n"
      "            if items[i] == items[j]:\n                return True\n    return False\n"},
     {"test_listutil.py": "from listutil import has_duplicates\n\ndef test_small():\n    assert has_duplicates([1, 2, 1])\n    assert not has_duplicates([1, 2, 3])\n    assert not has_duplicates([])\n"},
     {"test_hidden_duplicates.py": DEADLINE + "\nfrom listutil import has_duplicates\n\n\ndef test_large_fast():\n"
      "    finished, value = _run_with_deadline(lambda: has_duplicates(list(range(200_000))), 1.0)\n    assert finished, 'did not finish within 1 second'\n    assert value is False\n\n\n"
      "def test_large_with_dup():\n    finished, value = _run_with_deadline(lambda: has_duplicates(list(range(200_000)) + [199_999]), 1.0)\n    assert finished and value is True\n"},
     {"listutil.py": "def has_duplicates(items):\n    seen = set()\n    for x in items:\n        if x in seen:\n            return True\n        seen.add(x)\n    return False\n"})

task("performance_prime_sieve", "Fast primes below n", "performance", "medium",
     "primes.primes_below(n) tests every number by trial division against all smaller numbers and is far\n"
     "too slow for n = 1_000_000. Return the same sorted list of primes < n, fast enough that n = 1_000_000\n"
     "finishes in under 2 seconds (e.g. a Sieve of Eratosthenes).",
     ["len(primes_below(1_000_000)) == 78498 in < 2 s", "primes_below(20) == [2, 3, 5, 7, 11, 13, 17, 19]", "primes_below(2) == []"],
     {"primes.py": "def primes_below(n):\n    out = []\n    for k in range(2, n):\n        if all(k % d for d in range(2, k)):\n            out.append(k)\n    return out\n"},
     {"test_primes.py": "from primes import primes_below\n\ndef test_small():\n    assert primes_below(20) == [2, 3, 5, 7, 11, 13, 17, 19]\n    assert primes_below(2) == []\n"},
     {"test_hidden_sieve.py": DEADLINE + "\nfrom primes import primes_below\n\n\ndef test_million():\n"
      "    finished, value = _run_with_deadline(lambda: primes_below(1_000_000), 2.0)\n    assert finished, 'did not finish within 2 seconds'\n"
      "    assert len(value) == 78498 and value[-1] == 999983\n\n\ndef test_edges():\n    assert primes_below(0) == [] and primes_below(3) == [2]\n"},
     {"primes.py": "def primes_below(n):\n    if n < 3:\n        return []\n    sieve = bytearray([1]) * n\n    sieve[0] = sieve[1] = 0\n"
      "    for i in range(2, int(n ** 0.5) + 1):\n        if sieve[i]:\n            sieve[i * i::i] = bytearray(len(range(i * i, n, i)))\n"
      "    return [i for i in range(n) if sieve[i]]\n"})

task("performance_pair_sums", "Count pairs with a target sum in linear time", "performance", "medium",
     "pairs.count_pairs(nums, target) counts index pairs i < j with nums[i] + nums[j] == target using a\n"
     "nested loop. Make it linear-time so 100_000 numbers finish in under a second; duplicates must be\n"
     "counted correctly.",
     ["count_pairs([1, 1, 1], 2) == 3", "count_pairs([1, 2, 3, 4], 5) == 2", "100_000 items in < 1 s"],
     {"pairs.py": "def count_pairs(nums, target):\n    count = 0\n    for i in range(len(nums)):\n        for j in range(i + 1, len(nums)):\n"
      "            if nums[i] + nums[j] == target:\n                count += 1\n    return count\n"},
     {"test_pairs.py": "from pairs import count_pairs\n\ndef test_small():\n    assert count_pairs([1, 2, 3, 4], 5) == 2\n    assert count_pairs([1, 1, 1], 2) == 3\n    assert count_pairs([], 1) == 0\n"},
     {"test_hidden_pairs.py": DEADLINE + "\nfrom pairs import count_pairs\n\n\ndef test_large_fast():\n    nums = list(range(100_000))\n"
      "    finished, value = _run_with_deadline(lambda: count_pairs(nums, 99_999), 1.0)\n    assert finished, 'did not finish within 1 second'\n    assert value == 50_000\n\n\n"
      "def test_duplicates():\n    assert count_pairs([2, 2, 2, 2], 4) == 6\n    assert count_pairs([3, 3, 0, 6], 6) == 2\n"},
     {"pairs.py": "from collections import Counter\n\n\ndef count_pairs(nums, target):\n    seen = Counter()\n    count = 0\n    for x in nums:\n"
      "        count += seen[target - x]\n        seen[x] += 1\n    return count\n"})

# ============================================================== api
ITEMS_REPO = "ITEMS = {1: {'id': 1, 'name': 'apple'}}\n\n\n"
task("api_create_item", "Add POST /items", "api", "medium",
     "api.handle(method, path) serves GET /items/<id>. Add an optional body argument: handle(method, path, body=None).\n"
     "POST /items with body {'name': ...} creates an item with the next integer id and returns\n"
     "(201, {'id': id, 'name': name}); a missing or blank name returns (400, {'error': 'name required'}).\n"
     "The created item is then readable with GET /items/<id>.",
     ["POST /items -> 201 with new id", "missing name -> 400", "GET /items/<new id> returns it"],
     {"api.py": ITEMS_REPO + "def handle(method, path):\n    if method == 'GET' and path.startswith('/items/'):\n        key = path.removeprefix('/items/')\n"
      "        item = ITEMS.get(int(key)) if key.isdigit() else None\n        return (200, item) if item else (404, {'error': 'not found'})\n    return 404, {'error': 'not found'}\n"},
     {"test_api.py": "from api import handle\n\ndef test_get():\n    assert handle('GET', '/items/1') == (200, {'id': 1, 'name': 'apple'})\n    assert handle('GET', '/items/99')[0] == 404\n"},
     {"test_hidden_create.py": "from api import handle\n\ndef test_create_and_read():\n    status, body = handle('POST', '/items', {'name': 'pear'})\n    assert status == 201 and body['name'] == 'pear'\n"
      "    assert body['id'] > 1\n    assert handle('GET', f\"/items/{body['id']}\") == (200, body)\n\n"
      "def test_validation():\n    assert handle('POST', '/items', {}) == (400, {'error': 'name required'})\n    assert handle('POST', '/items', {'name': '  '}) == (400, {'error': 'name required'})\n"},
     {"api.py": ITEMS_REPO + "def handle(method, path, body=None):\n    if method == 'POST' and path == '/items':\n        name = (body or {}).get('name', '')\n"
      "        if not isinstance(name, str) or not name.strip():\n            return 400, {'error': 'name required'}\n        new_id = max(ITEMS, default=0) + 1\n"
      "        ITEMS[new_id] = {'id': new_id, 'name': name}\n        return 201, ITEMS[new_id]\n    if method == 'GET' and path.startswith('/items/'):\n"
      "        key = path.removeprefix('/items/')\n        item = ITEMS.get(int(key)) if key.isdigit() else None\n        return (200, item) if item else (404, {'error': 'not found'})\n"
      "    return 404, {'error': 'not found'}\n"})

task("api_path_parameters", "Path parameters in the router", "api", "hard",
     "router.Router matches only exact paths. Support path parameters: a pattern segment written {name}\n"
     "matches any single non-empty segment and is passed to the handler as a keyword argument (string).\n"
     "Static routes keep working; a path with a different number of segments does not match (404).\n"
     "dispatch returns (status, body) and handlers return the body.",
     ["/users/{id} matches /users/42 with id='42'", "/users/42/extra -> 404", "multiple params: /a/{x}/b/{y}"],
     {"router.py": "class Router:\n    def __init__(self):\n        self._routes = {}\n\n    def add(self, method, pattern, handler):\n"
      "        self._routes[(method, pattern)] = handler\n\n    def dispatch(self, method, path):\n        handler = self._routes.get((method, path))\n"
      "        if handler is None:\n            return 404, {'error': 'not found'}\n        return 200, handler()\n"},
     {"test_router.py": "from router import Router\n\ndef test_static():\n    r = Router()\n    r.add('GET', '/ping', lambda: 'pong')\n    assert r.dispatch('GET', '/ping') == (200, 'pong')\n"
      "    assert r.dispatch('GET', '/nope')[0] == 404\n"},
     {"test_hidden_params.py": "from router import Router\n\ndef test_param():\n    r = Router()\n    r.add('GET', '/users/{id}', lambda id: {'user': id})\n"
      "    assert r.dispatch('GET', '/users/42') == (200, {'user': '42'})\n    assert r.dispatch('GET', '/users/42/extra')[0] == 404\n    assert r.dispatch('GET', '/users/')[0] == 404\n\n"
      "def test_multiple():\n    r = Router()\n    r.add('GET', '/a/{x}/b/{y}', lambda x, y: x + y)\n    assert r.dispatch('GET', '/a/1/b/2') == (200, '12')\n\n"
      "def test_method_and_static():\n    r = Router()\n    r.add('GET', '/ping', lambda: 'pong')\n    r.add('GET', '/users/{id}', lambda id: id)\n"
      "    assert r.dispatch('POST', '/users/1')[0] == 404\n    assert r.dispatch('GET', '/ping') == (200, 'pong')\n"},
     {"router.py": "class Router:\n    def __init__(self):\n        self._routes = []\n\n    def add(self, method, pattern, handler):\n"
      "        self._routes.append((method, pattern.strip('/').split('/'), handler))\n\n    def dispatch(self, method, path):\n        parts = path.strip('/').split('/')\n"
      "        for m, segs, handler in self._routes:\n            if m != method or len(segs) != len(parts):\n                continue\n            params = {}\n"
      "            for seg, part in zip(segs, parts):\n                if seg.startswith('{') and seg.endswith('}'):\n                    if not part:\n                        break\n"
      "                    params[seg[1:-1]] = part\n                elif seg != part:\n                    break\n            else:\n                return 200, handler(**params)\n"
      "        return 404, {'error': 'not found'}\n"})

task("api_rate_limiter", "Per-client rate limiter", "api", "medium",
     "ratelimit.RateLimiter(limit, window_seconds, clock=time.monotonic).allow(client_id) currently always\n"
     "returns True. Implement a sliding window: a client may make at most `limit` allowed requests in any\n"
     "window of `window_seconds`; denied requests do not count. Clients are independent. Use the injected\n"
     "clock so it can be tested.",
     ["first `limit` requests allowed, next denied", "allowed again after the window passes", "clients independent"],
     {"ratelimit.py": "import time\n\n\nclass RateLimiter:\n    def __init__(self, limit, window_seconds, clock=time.monotonic):\n        self.limit = limit\n"
      "        self.window = window_seconds\n        self.clock = clock\n\n    def allow(self, client_id):\n        return True\n"},
     {"test_ratelimit.py": "from ratelimit import RateLimiter\n\ndef test_first_allowed():\n    assert RateLimiter(3, 60).allow('a')\n"},
     {"test_hidden_ratelimit.py": "from ratelimit import RateLimiter\n\nclass Clock:\n    def __init__(self):\n        self.t = 0.0\n    def __call__(self):\n        return self.t\n\n"
      "def test_limit_and_window():\n    c = Clock()\n    rl = RateLimiter(3, 10, clock=c)\n    assert [rl.allow('a') for _ in range(4)] == [True, True, True, False]\n"
      "    c.t = 10.5\n    assert rl.allow('a')\n\ndef test_clients_independent():\n    c = Clock()\n    rl = RateLimiter(1, 10, clock=c)\n"
      "    assert rl.allow('a') and rl.allow('b') and not rl.allow('a')\n\ndef test_denied_not_counted():\n    c = Clock()\n    rl = RateLimiter(1, 10, clock=c)\n"
      "    rl.allow('a')\n    c.t = 5\n    assert not rl.allow('a')\n    c.t = 10.1\n    assert rl.allow('a')\n"},
     {"ratelimit.py": "import time\nfrom collections import defaultdict, deque\n\n\nclass RateLimiter:\n    def __init__(self, limit, window_seconds, clock=time.monotonic):\n"
      "        self.limit = limit\n        self.window = window_seconds\n        self.clock = clock\n        self._hits = defaultdict(deque)\n\n"
      "    def allow(self, client_id):\n        now = self.clock()\n        hits = self._hits[client_id]\n        while hits and hits[0] <= now - self.window:\n"
      "            hits.popleft()\n        if len(hits) >= self.limit:\n            return False\n        hits.append(now)\n        return True\n"})

# ============================================================== database
SCHEMA = ("import sqlite3\n\n\ndef connect():\n    conn = sqlite3.connect(':memory:')\n    conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)')\n"
          "    conn.execute(\"INSERT INTO users (name) VALUES ('ada')\")\n    return conn\n")
task("database_add_column_migration", "Idempotent migration: add email column", "database", "medium",
     "db.py creates a users(id, name) table. Add migrate(conn) that adds a nullable TEXT column `email`\n"
     "to users. It must be idempotent (running it twice is fine) and keep existing rows.",
     ["after migrate, users has an email column", "migrate twice does not raise", "existing rows kept"],
     {"db.py": SCHEMA},
     {"test_db.py": "from db import connect\n\ndef test_seed():\n    assert connect().execute('SELECT name FROM users').fetchall() == [('ada',)]\n"},
     {"test_hidden_migrate.py": "from db import connect, migrate\n\ndef _cols(conn):\n    return [r[1] for r in conn.execute('PRAGMA table_info(users)')]\n\n"
      "def test_adds_column():\n    conn = connect()\n    migrate(conn)\n    assert 'email' in _cols(conn)\n\ndef test_idempotent_and_keeps_rows():\n    conn = connect()\n"
      "    migrate(conn)\n    migrate(conn)\n    assert _cols(conn).count('email') == 1\n    assert conn.execute('SELECT name, email FROM users').fetchall() == [('ada', None)]\n"},
     {"db.py": SCHEMA + "\n\ndef migrate(conn):\n    cols = {r[1] for r in conn.execute('PRAGMA table_info(users)')}\n    if 'email' not in cols:\n"
      "        conn.execute('ALTER TABLE users ADD COLUMN email TEXT')\n        conn.commit()\n"})

BANK = ("import sqlite3\n\n\ndef connect():\n    conn = sqlite3.connect(':memory:')\n    conn.execute('CREATE TABLE accounts (id TEXT PRIMARY KEY, balance INTEGER NOT NULL)')\n"
        "    conn.executemany('INSERT INTO accounts VALUES (?, ?)', [('alice', 100), ('bob', 50)])\n    conn.commit()\n    return conn\n\n\n"
        "def balance(conn, account):\n    row = conn.execute('SELECT balance FROM accounts WHERE id = ?', (account,)).fetchone()\n    return row[0] if row else None\n\n\n")
task("database_atomic_transfer", "Atomic money transfer", "database", "hard",
     "bank.transfer(conn, src, dst, amount) runs two UPDATEs with no checks, so balances can go negative and a\n"
     "transfer to a missing account still debits the source. Make it atomic: raise ValueError and change\n"
     "nothing if amount <= 0, either account does not exist, or src has insufficient funds.",
     ["valid transfer moves money", "insufficient funds -> ValueError, balances unchanged", "unknown dst -> ValueError, src unchanged"],
     {"bank.py": BANK + "def transfer(conn, src, dst, amount):\n    conn.execute('UPDATE accounts SET balance = balance - ? WHERE id = ?', (amount, src))\n"
      "    conn.execute('UPDATE accounts SET balance = balance + ? WHERE id = ?', (amount, dst))\n    conn.commit()\n"},
     {"test_bank.py": "from bank import connect, balance, transfer\n\ndef test_transfer():\n    conn = connect()\n    transfer(conn, 'alice', 'bob', 30)\n"
      "    assert balance(conn, 'alice') == 70 and balance(conn, 'bob') == 80\n"},
     {"test_hidden_atomic.py": "import pytest\nfrom bank import connect, balance, transfer\n\ndef test_insufficient():\n    conn = connect()\n    with pytest.raises(ValueError):\n"
      "        transfer(conn, 'bob', 'alice', 500)\n    assert balance(conn, 'bob') == 50 and balance(conn, 'alice') == 100\n\n"
      "def test_unknown_account():\n    conn = connect()\n    with pytest.raises(ValueError):\n        transfer(conn, 'alice', 'carol', 10)\n    assert balance(conn, 'alice') == 100\n\n"
      "def test_non_positive():\n    conn = connect()\n    with pytest.raises(ValueError):\n        transfer(conn, 'alice', 'bob', 0)\n    with pytest.raises(ValueError):\n"
      "        transfer(conn, 'alice', 'bob', -5)\n    assert balance(conn, 'alice') == 100\n"},
     {"bank.py": BANK + "def transfer(conn, src, dst, amount):\n    if amount <= 0:\n        raise ValueError('amount must be positive')\n    with conn:\n"
      "        src_bal = balance(conn, src)\n        if src_bal is None or balance(conn, dst) is None:\n            raise ValueError('unknown account')\n"
      "        if src_bal < amount:\n            raise ValueError('insufficient funds')\n"
      "        conn.execute('UPDATE accounts SET balance = balance - ? WHERE id = ?', (amount, src))\n"
      "        conn.execute('UPDATE accounts SET balance = balance + ? WHERE id = ?', (amount, dst))\n"})

ORDERS = ("import sqlite3\n\n\ndef connect():\n    conn = sqlite3.connect(':memory:')\n    conn.executescript('''\n"
          "        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);\n        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, total REAL);\n"
          "        INSERT INTO customers VALUES (1, 'ada'), (2, 'bob'), (3, 'cy'), (4, 'dee');\n"
          "        INSERT INTO orders (customer_id, total) VALUES (1, 10), (1, 15), (2, 25), (3, 5), (3, 40);\n    ''')\n    return conn\n\n\n"
          "def order_count(conn):\n    return conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]\n")
task("database_top_customers", "Top customers by spend", "database", "medium",
     "orders.py has customers and orders tables. Add top_customers(conn, n) returning a list of (name, total_spent)\n"
     "tuples for the n customers with the highest total order value, highest first, ties broken by name.\n"
     "Customers with no orders are excluded. Compute it in SQL (GROUP BY), not in Python loops.",
     ["top_customers(conn, 2) == [('cy', 45.0), ('ada', 25.0)]", "ties ordered by name", "customers without orders excluded"],
     {"orders.py": ORDERS},
     {"test_orders.py": "from orders import connect, order_count\n\ndef test_count():\n    assert order_count(connect()) == 5\n"},
     {"test_hidden_top.py": "from orders import connect, top_customers\n\ndef test_top_two():\n    assert top_customers(connect(), 2) == [('cy', 45.0), ('ada', 25.0)]\n\n"
      "def test_tie_and_exclusion():\n    assert top_customers(connect(), 10) == [('cy', 45.0), ('ada', 25.0), ('bob', 25.0)]\n"},
     {"orders.py": ORDERS + "\n\ndef top_customers(conn, n):\n    rows = conn.execute('''\n        SELECT c.name, SUM(o.total) AS spent FROM customers c\n"
      "        JOIN orders o ON o.customer_id = c.id\n        GROUP BY c.id ORDER BY spent DESC, c.name ASC LIMIT ?\n    ''', (n,))\n"
      "    return [(name, float(spent)) for name, spent in rows]\n"})

# ============================================================== error_handling
task("error_handling_retry", "Retry transient connection errors", "error_handling", "medium",
     "net.fetch_with_retry(fn, attempts=3) calls fn() once. It must retry only on ConnectionError, calling fn\n"
     "at most `attempts` times, return the first successful result, and re-raise the last ConnectionError if\n"
     "every attempt fails. Other exceptions propagate immediately without retrying.",
     ["fails twice then succeeds -> result", "always failing -> ConnectionError after exactly 3 calls", "ValueError not retried"],
     {"net.py": "def fetch_with_retry(fn, attempts=3):\n    return fn()\n"},
     {"test_net.py": "from net import fetch_with_retry\n\ndef test_success():\n    assert fetch_with_retry(lambda: 42) == 42\n"},
     {"test_hidden_retry.py": "import pytest\nfrom net import fetch_with_retry\n\ndef _flaky(fails, exc=ConnectionError):\n    calls = []\n    def fn():\n        calls.append(1)\n"
      "        if len(calls) <= fails:\n            raise exc('boom')\n        return 'ok'\n    return fn, calls\n\n"
      "def test_recovers():\n    fn, calls = _flaky(2)\n    assert fetch_with_retry(fn) == 'ok' and len(calls) == 3\n\n"
      "def test_gives_up():\n    fn, calls = _flaky(99)\n    with pytest.raises(ConnectionError):\n        fetch_with_retry(fn, attempts=3)\n    assert len(calls) == 3\n\n"
      "def test_other_errors_not_retried():\n    fn, calls = _flaky(99, ValueError)\n    with pytest.raises(ValueError):\n        fetch_with_retry(fn)\n    assert len(calls) == 1\n"},
     {"net.py": "def fetch_with_retry(fn, attempts=3):\n    last = None\n    for _ in range(attempts):\n        try:\n            return fn()\n"
      "        except ConnectionError as e:\n            last = e\n    raise last\n"})

task("error_handling_settings_file", "Clear errors when loading settings", "error_handling", "medium",
     "settings.load_settings(path) lets FileNotFoundError and json.JSONDecodeError escape. A missing file must\n"
     "return {}. Invalid JSON, or JSON whose top level is not an object, must raise settings.SettingsError (a new\n"
     "exception class) whose message includes the file path.",
     ["missing file -> {}", "invalid JSON -> SettingsError mentioning the path", "non-object JSON -> SettingsError"],
     {"settings.py": "import json\n\n\ndef load_settings(path):\n    with open(path) as f:\n        return json.load(f)\n"},
     {"test_settings.py": "from settings import load_settings\n\ndef test_valid(tmp_path):\n    p = tmp_path / 's.json'\n    p.write_text('{\"debug\": true}')\n    assert load_settings(p) == {'debug': True}\n"},
     {"test_hidden_settings.py": "import pytest\nimport settings\n\ndef test_missing(tmp_path):\n    assert settings.load_settings(tmp_path / 'nope.json') == {}\n\n"
      "def test_invalid(tmp_path):\n    p = tmp_path / 'bad.json'\n    p.write_text('{nope')\n    with pytest.raises(settings.SettingsError) as e:\n        settings.load_settings(p)\n"
      "    assert 'bad.json' in str(e.value)\n\ndef test_not_object(tmp_path):\n    p = tmp_path / 'list.json'\n    p.write_text('[1, 2]')\n    with pytest.raises(settings.SettingsError):\n"
      "        settings.load_settings(p)\n"},
     {"settings.py": "import json\n\n\nclass SettingsError(Exception):\n    pass\n\n\ndef load_settings(path):\n    try:\n        with open(path) as f:\n            data = json.load(f)\n"
      "    except FileNotFoundError:\n        return {}\n    except json.JSONDecodeError as e:\n        raise SettingsError(f\"invalid JSON in {path}: {e}\") from e\n"
      "    if not isinstance(data, dict):\n        raise SettingsError(f\"{path}: top level must be an object\")\n    return data\n"})

task("error_handling_order_validation", "Validate order inputs", "error_handling", "easy",
     "orders.create_order(qty, unit_price) returns {'qty', 'unit_price', 'total'} without validating anything.\n"
     "Raise TypeError if qty is not an int (bool is not accepted), ValueError('qty must be positive') if qty < 1,\n"
     "and ValueError('unit_price must not be negative') if unit_price < 0.",
     ["create_order(2, 5.0)['total'] == 10.0", "qty 0 -> ValueError", "qty 1.5 / True -> TypeError", "negative price -> ValueError"],
     {"orders.py": "def create_order(qty, unit_price):\n    return {'qty': qty, 'unit_price': unit_price, 'total': round(qty * unit_price, 2)}\n"},
     {"test_orders.py": "from orders import create_order\n\ndef test_ok():\n    assert create_order(2, 5.0)['total'] == 10.0\n"},
     {"test_hidden_validation.py": "import pytest\nfrom orders import create_order\n\ndef test_qty():\n    with pytest.raises(ValueError, match='qty must be positive'):\n        create_order(0, 1)\n\n"
      "@pytest.mark.parametrize('bad', [1.5, '2', True])\ndef test_qty_type(bad):\n    with pytest.raises(TypeError):\n        create_order(bad, 1)\n\n"
      "def test_price():\n    with pytest.raises(ValueError, match='unit_price must not be negative'):\n        create_order(1, -0.01)\n    assert create_order(1, 0)['total'] == 0\n"},
     {"orders.py": "def create_order(qty, unit_price):\n    if isinstance(qty, bool) or not isinstance(qty, int):\n        raise TypeError('qty must be an int')\n    if qty < 1:\n"
      "        raise ValueError('qty must be positive')\n    if unit_price < 0:\n        raise ValueError('unit_price must not be negative')\n"
      "    return {'qty': qty, 'unit_price': unit_price, 'total': round(qty * unit_price, 2)}\n"})

# ============================================================== configuration
task("config_bool_parsing", "Parse boolean settings correctly", "configuration", "easy",
     "config.get_bool(env, key, default=False) uses bool(env.get(key)), so 'false' and '0' are True. Accept\n"
     "'1', 'true', 'yes', 'on' as True and '0', 'false', 'no', 'off' as False (case-insensitive, surrounding\n"
     "whitespace ignored). A missing key returns default; any other value raises ValueError naming the key.",
     ["'false' -> False", "' YES ' -> True", "missing -> default", "'maybe' -> ValueError"],
     {"config.py": "def get_bool(env, key, default=False):\n    if key not in env:\n        return default\n    return bool(env.get(key))\n"},
     {"test_config.py": "from config import get_bool\n\ndef test_true_and_default():\n    assert get_bool({'A': 'true'}, 'A') is True\n    assert get_bool({}, 'A', default=True) is True\n"},
     {"test_hidden_bool.py": "import pytest\nfrom config import get_bool\n\n@pytest.mark.parametrize('v', ['0', 'false', 'No', 'OFF', ' false '])\ndef test_false(v):\n"
      "    assert get_bool({'K': v}, 'K', default=True) is False\n\n@pytest.mark.parametrize('v', ['1', 'TRUE', ' yes ', 'on'])\ndef test_true(v):\n    assert get_bool({'K': v}, 'K') is True\n\n"
      "def test_invalid():\n    with pytest.raises(ValueError, match='K'):\n        get_bool({'K': 'maybe'}, 'K')\n"},
     {"config.py": "TRUE = {'1', 'true', 'yes', 'on'}\nFALSE = {'0', 'false', 'no', 'off'}\n\n\ndef get_bool(env, key, default=False):\n    if key not in env:\n        return default\n"
      "    v = str(env[key]).strip().lower()\n    if v in TRUE:\n        return True\n    if v in FALSE:\n        return False\n    raise ValueError(f\"{key}: not a boolean: {env[key]!r}\")\n"})

task("config_layered_merge", "Deep-merge layered configuration", "configuration", "medium",
     "config.merge_config(*layers) combines config dicts with {**a, **b}, so a nested section in a later layer\n"
     "replaces the whole section. Deep-merge instead: nested dicts merge recursively, later layers win for\n"
     "non-dict values, and none of the input dicts are modified.",
     ["nested keys from earlier layers survive", "later scalar wins", "inputs not mutated"],
     {"config.py": "def merge_config(*layers):\n    out = {}\n    for layer in layers:\n        out = {**out, **layer}\n    return out\n"},
     {"test_config.py": "from config import merge_config\n\ndef test_flat():\n    assert merge_config({'a': 1, 'b': 2}, {'b': 3}) == {'a': 1, 'b': 3}\n"},
     {"test_hidden_merge.py": "import copy\nfrom config import merge_config\n\ndef test_nested():\n    defaults = {'db': {'host': 'localhost', 'port': 5432}, 'debug': False}\n"
      "    env = {'db': {'port': 6543}, 'debug': True}\n    assert merge_config(defaults, env) == {'db': {'host': 'localhost', 'port': 6543}, 'debug': True}\n\n"
      "def test_three_layers():\n    assert merge_config({'a': {'b': {'c': 1, 'd': 2}}}, {'a': {'b': {'c': 9}}}, {'a': {'e': 3}}) == {'a': {'b': {'c': 9, 'd': 2}, 'e': 3}}\n\n"
      "def test_no_mutation():\n    a = {'x': {'y': 1}}\n    b = {'x': {'z': 2}}\n    snap = copy.deepcopy((a, b))\n    out = merge_config(a, b)\n    out['x']['y'] = 99\n"
      "    assert (a, b) == snap\n"},
     {"config.py": "import copy\n\n\ndef _merge(base, over):\n    for k, v in over.items():\n        if isinstance(v, dict) and isinstance(base.get(k), dict):\n"
      "            _merge(base[k], v)\n        else:\n            base[k] = copy.deepcopy(v)\n\n\ndef merge_config(*layers):\n    out = {}\n"
      "    for layer in layers:\n        _merge(out, layer)\n    return out\n"})


def main():
    assert len(TASKS) == 30, len(TASKS)
    assert len({t["id"] for t in TASKS}) == 30
    for t in TASKS:
        d = ROOT / t["id"]
        assert not d.exists(), f"refusing to overwrite {d}"
        (d / "repo" / "tests").mkdir(parents=True)
        (d / "hidden_tests").mkdir()
        (d / "solution").mkdir()
        (d / "repo" / "pyproject.toml").write_text(PYPROJECT)
        for name, body in t["repo"].items():
            (d / "repo" / name).write_text(body)
        for name, body in t["visible"].items():
            (d / "repo" / "tests" / name).write_text(body)
        for name, body in t["hidden"].items():
            (d / "hidden_tests" / name).write_text(body)
        for name, body in t["solution"].items():
            (d / "solution" / name).write_text(body)
        (d / "task.json").write_text(json.dumps({
            "id": t["id"], "title": t["title"], "category": t["category"], "difficulty": t["difficulty"],
            "requirement": t["requirement"], "acceptance_criteria": t["criteria"], "ground_truth": "",
            "timeout_seconds": 120,
        }, indent=2) + "\n")
    print(f"wrote {len(TASKS)} tasks to {ROOT}")


if __name__ == "__main__":
    main()
