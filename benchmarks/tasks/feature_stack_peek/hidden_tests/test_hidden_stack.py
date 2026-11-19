import pytest
from stack import Stack

def test_peek():
    s = Stack()
    s.push('a')
    s.push('b')
    assert s.peek() == 'b'
    assert len(s) == 2

def test_empty():
    s = Stack()
    assert s.is_empty() and len(s) == 0
    with pytest.raises(IndexError, match='empty stack'):
        s.pop()
    with pytest.raises(IndexError, match='empty stack'):
        s.peek()
