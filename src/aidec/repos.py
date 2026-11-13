"""レポの様子。situation-room（`sr`）の状況図から、開いている Issue と計画の進み具合を並べる。

数字は並べるだけで、評価しない（積み上がりは使っている印）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, datetime, timedelta

SR = "sr"
ACTIVE_DAYS = 14
FETCH_TIMEOUT = 120


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _line(p: dict, iss: dict, today: date, last_d: date | None, stalled: bool) -> str:
    name = str(p.get("slug", "?")).rsplit("/", 1)[-1]
    text = f"{name} 開 {iss.get('open', 0)}"
    if iss.get("oldest_open_at"):
        text += f"（最古 {_md(_dt(iss['oldest_open_at']).date())}）"
    for pl in iss.get("plans") or []:
        done, total = pl.get("done"), pl.get("total")
        prog = f"{done}/{total}" if done is not None and total is not None else "計画が見つからない"
        text += f" #{pl.get('issue')} {prog}"
    if stalled and last_d is not None:
        text += f" 最後に触った {last_d.year}/{_md(last_d)}"
    if iss.get("fetched_at"):
        fetched = _dt(iss["fetched_at"]).date()
        if fetched < today:
            text += f"（{_md(fetched)} 時点）"
    return f"- {text}"


def format_repos(doc: dict, today: date) -> tuple[list[str], list[str]]:
    """(動いている, 止まっている)。

    動いている: ACTIVE_DAYS 日以内に触ったもの。止まっている: それより前で、開いた Issue があるもの。
    どちらも最後に触った順。開いた Issue が無く止まっているものは出さない。
    """
    active, stalled = [], []
    for p in doc.get("projects") or []:
        iss = p.get("issues")
        if not iss:
            continue
        last = p.get("last_activity")
        last_d = _dt(last).date() if last else None
        if last_d is not None and last_d >= today - timedelta(days=ACTIVE_DAYS):
            active.append((last, _line(p, iss, today, last_d, False)))
        elif iss.get("open"):
            stalled.append((last or "", _line(p, iss, today, last_d, True)))
    return ([t for _, t in sorted(active, reverse=True)],
            [t for _, t in sorted(stalled, reverse=True)])


def repos_section(today: date, fetch: bool = True) -> tuple[list[str], list[str]] | None:
    """sr が無ければ None（欄を出さない）。取得の失敗は前回の値のまま出す。"""
    if shutil.which(SR) is None:
        return None
    notes = []
    if fetch:
        try:
            r = subprocess.run([SR, "issues", "fetch"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=FETCH_TIMEOUT)
            if r.returncode != 0:
                notes.append("- 一部のレポは取得できず、前回の値（日付を添える）")
        except (OSError, subprocess.TimeoutExpired):
            notes.append("- Issue を取得できず、前回の値（日付を添える）")
    try:
        r = subprocess.run([SR, "list", "--format", "json"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        doc = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        doc = None
    if not isinstance(doc, dict):
        return ["- sr の状況図を読めない"], []
    active, stalled = format_repos(doc, today)
    return active + notes, stalled
