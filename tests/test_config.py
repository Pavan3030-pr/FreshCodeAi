import os

from app.config import _bool, _clean, _env, _int


def test_inline_comments_and_comment_only_values_are_ignored():
    assert _clean("  # if set, /api requires it") == ""
    assert _clean("1   # enabled") == "1"
    assert _clean("http://localhost:4000/v1") == "http://localhost:4000/v1"
    assert _clean("abc#def") == "abc#def"  # a # without preceding whitespace is part of the value


def test_env_helpers_parse_safely():
    os.environ["FC_T1"] = "              # a comment"
    os.environ["FC_T2"] = "7 # seven"
    os.environ["FC_T3"] = "not-a-number"
    try:
        assert _env("FC_T1") == "" and _int("FC_T2", 1, 0, 10) == 7
        assert _int("FC_T3", 5, 0, 10) == 5 and _int("FC_T2", 1, 0, 3) == 3
        assert _bool("FC_T1", True) is True and _bool("FC_T2", False) is False
    finally:
        for k in ("FC_T1", "FC_T2", "FC_T3"):
            os.environ.pop(k, None)
