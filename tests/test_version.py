import pytest

from cfbtui import __version__
from cfbtui.version import bump, fib_next, is_fib, is_fibver, parse


def test_fib_next_walks_the_sequence_without_the_duplicate_one():
    seq = []
    n = 0
    for _ in range(10):
        n = fib_next(n)
        seq.append(n)
    assert seq == [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]


def test_fib_next_from_non_fibonacci_jumps_to_next_fibonacci():
    assert fib_next(4) == 5
    assert fib_next(9) == 13
    assert fib_next(100) == 144


def test_is_fib():
    assert [n for n in range(25) if is_fib(n)] == [0, 1, 2, 3, 5, 8, 13, 21]


def test_bump_each_part_resets_lower_parts():
    assert bump("0.1.0", "patch") == "0.1.1"
    assert bump("0.1.1", "patch") == "0.1.2"
    assert bump("0.1.2", "patch") == "0.1.3"
    assert bump("0.1.3", "patch") == "0.1.5"
    assert bump("0.1.21", "minor") == "0.2.0"
    assert bump("0.8.34", "minor") == "0.13.0"
    assert bump("0.13.5", "major") == "1.0.0"
    assert bump("1.0.0", "major") == "2.0.0"


def test_bump_rejects_unknown_part():
    with pytest.raises(ValueError):
        bump("0.1.0", "flavor")


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse("1.2")
    with pytest.raises(ValueError):
        parse("a.b.c")


def test_is_fibver():
    assert is_fibver("0.1.0")
    assert is_fibver("1.13.144")
    assert not is_fibver("0.4.0")
    assert not is_fibver("1.2.3.4")


def test_package_version_is_fibver():
    assert is_fibver(__version__), f"{__version__} is not FibVer"
