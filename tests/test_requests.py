from datetime import date

import pytest

from aidec.requests import (Request, RequestError, format_request, load_requests, next_request_id,
                               parse_request, write_request)

R = Request("2027-10-01-macro-mon", "macro-mon", date(2027, 10, 1), date(2027, 10, 11), "open",
            [date(2027, 10, 18)], "10/18（第 4 回）: 学会（○○）（10/18〜10/20）\n")


def test_format():
    assert format_request(R) == (
        "---\nid: 2027-10-01-macro-mon\nto: macro-mon\nissued: 2027-10-01\ndecide_by: 2027-10-11\n"
        "status: open\ndates: [2027-10-18]\n---\n10/18（第 4 回）: 学会（○○）（10/18〜10/20）\n")


def test_round_trip(tmp_path):
    p = write_request(tmp_path / "requests", R)
    assert p.name == "2027-10-01-macro-mon.md"
    assert b"\r\n" not in p.read_bytes()
    assert load_requests(tmp_path / "requests") == [R]


def test_parse_accepts_comments_and_crlf():
    text = format_request(R).replace("status: open", "status: open   # open → reported → closed")
    assert parse_request(text.replace("\n", "\r\n"), "x") == R


def test_write_refuses_to_overwrite(tmp_path):
    write_request(tmp_path, R)
    with pytest.raises(RequestError, match="既にある"):
        write_request(tmp_path, R)


def test_next_id(tmp_path):
    assert next_request_id(tmp_path, date(2027, 10, 1), "macro-mon") == "2027-10-01-macro-mon"
    write_request(tmp_path, R)
    assert next_request_id(tmp_path, date(2027, 10, 1), "macro-mon") == "2027-10-01-macro-mon-2"


def test_missing_dir_has_no_requests(tmp_path):
    assert load_requests(tmp_path / "none") == []


@pytest.mark.parametrize("old, new, message", [
    ("status: open", "status: done", "status"),
    ("---\nid", "id", "--- で始まる"),
    ("to: macro-mon\n", "", "to が無い"),
])
def test_bad_request(old, new, message):
    with pytest.raises(RequestError, match=message):
        parse_request(format_request(R).replace(old, new, 1), "x.md")


def test_impossible_date_names_the_file():
    with pytest.raises(RequestError, match="x.md"):
        parse_request(format_request(R).replace("2027-10-11", "2027-10-32"), "x.md")
