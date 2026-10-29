"""
Simple calculator module used as a test fixture for VEXA's tool layer.

This is intentionally minimal so tests are deterministic and fast.
"""


def add(a: float, b: float) -> float:
    """Return a + b."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return a - b."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Return a * b."""
    return a * b


def divide(a: float, b: float) -> float:
    """Return a / b. Raises ZeroDivisionError if b is zero."""
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return a / b
