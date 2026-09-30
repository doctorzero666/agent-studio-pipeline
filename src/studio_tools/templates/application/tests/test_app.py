import pytest

from app import greet


def test_greeting():
    assert greet("Studio") == "Hello, Studio!"


def test_empty_name():
    with pytest.raises(ValueError):
        greet(" ")
