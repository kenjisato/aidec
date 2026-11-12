from aidec import yamlio


def test_dump_writes_lf_and_utf8(tmp_path):
    p = tmp_path / "a.yaml"
    yamlio.dump({"title": "学会（○○）", "items": [1, 2]}, p)
    raw = p.read_bytes()
    assert b"\r\n" not in raw
    assert "学会（○○）".encode("utf-8") in raw


def test_round_trip_keeps_comments_and_flow_style(tmp_path):
    p = tmp_path / "a.yaml"
    text = "a: 1  # メモ\nb:\n  - {n: 1, mode: zoom}\n"
    p.write_text(text, encoding="utf-8", newline="\n")
    data = yamlio.load(p)
    data["a"] = 2
    yamlio.dump(data, p)
    assert p.read_text(encoding="utf-8") == "a: 2  # メモ\nb:\n  - {n: 1, mode: zoom}\n"


def test_flow_helpers():
    out = yamlio.dumps({"m": yamlio.flow_map({"n": 1, "d": 2}),
                        "days": yamlio.flow_seq([1, 2])})
    assert out == "m: {n: 1, d: 2}\ndays: [1, 2]\n"
