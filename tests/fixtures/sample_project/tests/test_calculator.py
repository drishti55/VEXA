"""Tests for the sample calculator module."""
import sys
import os

# Make src importable when pytest runs from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from calculator import add, divide, multiply, subtract


class TestAdd:
    def test_positive(self):
        assert add(2, 3) == 5

    def test_negative(self):
        assert add(-1, -1) == -2

    def test_float(self):
        assert add(0.1, 0.2) == pytest.approx(0.3)


class TestSubtract:
    def test_basic(self):
        assert subtract(10, 4) == 6

    def test_result_negative(self):
        assert subtract(1, 5) == -4


class TestMultiply:
    def test_basic(self):
        assert multiply(3, 4) == 12

    def test_by_zero(self):
        assert multiply(99, 0) == 0


class TestDivide:
    def test_basic(self):
        assert divide(10, 2) == 5.0

    def test_divide_by_zero(self):
        with pytest.raises(ZeroDivisionError):
            divide(5, 0)
