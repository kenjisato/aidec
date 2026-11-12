import re
from datetime import date, datetime, timezone

from conftest import write
from aidec import inbox


def _item(ref="20271105-macro-mon-a1b2c3", **kw):
    base = dict(ref=ref, verb="raise", course="macro-mon", cls="A", session=5,
                received=datetime(2027, 11, 5, 9, 30, tzinfo=timezone.utc), no_reply=False,
                text="第 5 回を補講日に移したい。\n理由: 学会")
    return inbox.Item(**{**base, **kw})


def test_write_then_load_round_trips(tmp_path):
    items = [_item(), _item("20271106-macro-mon-ffffff", cls=None, session=None, no_reply=True)]
    for it in items:
        assert inbox.write(tmp_path, it) == tmp_path / "inbox" / f"{it.ref}.md"
    got, bad = inbox.load(tmp_path)
    assert bad == [] and sorted(got, key=lambda i: i.ref) == items


def test_new_ref_shape_and_uniqueness():
    a, b = inbox.new_ref(date(2027, 11, 5), "macro-mon"), inbox.new_ref(date(2027, 11, 5), "macro-mon")
    assert re.fullmatch(r"20271105-macro-mon-[0-9a-f]{6}", a) and a != b


def test_broken_file_is_named_and_others_load(tmp_path):
    inbox.write(tmp_path, _item())
    write(tmp_path / "inbox" / "broken.md", "no front matter\n")
    got, bad = inbox.load(tmp_path)
    assert [i.ref for i in got] == ["20271105-macro-mon-a1b2c3"] and bad == ["broken.md"]


def test_crlf_in_text_is_normalised(tmp_path):
    p = inbox.write(tmp_path, _item(text="a\r\nb\rc"))
    assert b"\r" not in p.read_bytes()
