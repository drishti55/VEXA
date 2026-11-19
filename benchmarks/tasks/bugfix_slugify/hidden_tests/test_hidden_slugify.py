from text import slugify

def test_punctuation():
    assert slugify('  Hello,  World! ') == 'hello-world'

def test_digits():
    assert slugify('Python 3.12 rocks') == 'python-3-12-rocks'

def test_only_symbols():
    assert slugify('!!!') == ''
