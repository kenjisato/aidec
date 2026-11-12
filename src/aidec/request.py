"""授業への依頼を手で出す。文面は workdesk-review などで授業担当者と決めたもの。"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from . import gitops
from .cli import KNOWN_ERRORS, error, setup_console
from .config import data_dir
from .data import load_year
from .requests import Request, next_request_id, write_request


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser(prog="request", description="授業への依頼を出す")
    ap.add_argument("year", type=int)
    ap.add_argument("--to", required=True, help="授業 id")
    ap.add_argument("--dates", nargs="*", type=date.fromisoformat, default=[], help="対応を決めてほしい日")
    ap.add_argument("--decide-by", type=date.fromisoformat, required=True)
    ap.add_argument("--body-file", type=Path, required=True)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        root = args.root or data_dir()
        if gitops.has_upstream(root):
            gitops.pull_ff_only(root)
        yd = load_year(root / str(args.year))
        if args.to not in {c.id for c in yd.courses}:
            error(f"courses.yaml に無い授業: {args.to}")
            return 1
        req = Request(next_request_id(root / "requests", args.today, args.to), args.to, args.today,
                      args.decide_by, "open", list(args.dates), args.body_file.read_text(encoding="utf-8"))
        path = write_request(root / "requests", req)
        gitops.commit_paths(root, [path.relative_to(root).as_posix()], f"依頼: {req.id}")
        if gitops.has_upstream(root) and gitops.is_ahead(root):
            gitops.push(root)
    except (*KNOWN_ERRORS, OSError) as e:
        error(str(e))
        return 1
    print(f"依頼 {req.id} を出した（{args.to}、期限 {args.decide_by.isoformat()}）")
    return 0
