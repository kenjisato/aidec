"""上位のコマンド（aidec supervise）。instructor-kit SPEC §8.8 の約束に答える。

stdin に JSON 1 個、stdout に JSON 1 行。授業の course-director が呼ぶ。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import gitops, inbox, yamlio
from .config import ConfigError, data_dir

PROTOCOL = 1
_DECLINED = {"protocol": PROTOCOL, "status": "declined"}
_MAX_HITS = 10


def _sessions_dir(year_dir: Path) -> tuple[Path, str]:
    """(年度の下の回のディレクトリの親, 回の名前の書式)。team.yaml の sessions.dir があればそれに従う。"""
    pattern = "{nn}"
    team = year_dir / "team.yaml"
    if team.is_file():
        try:
            doc = yamlio.load(team) or {}
            pattern = str((doc.get("sessions") or {}).get("dir") or pattern)
        except (yamlio.YamlError, AttributeError):
            pass
    return year_dir, pattern


def _course_map(year_dir: Path) -> Path:
    name = "course-map.md"
    team = year_dir / "team.yaml"
    if team.is_file():
        try:
            name = str((yamlio.load(team) or {}).get("map") or name)
        except (yamlio.YamlError, AttributeError):
            pass
    return year_dir / name


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[\s\W_]+", text) if len(w) >= 2]


def _course_repos(data: Path):
    """(授業の id, 名前, 授業レポの年度ディレクトリ)。クローンの無い授業は飛ばす。"""
    root = gitops.ghq_root()
    for yfile in sorted(data.glob("[0-9]*/courses.yaml")):
        if not yfile.parent.name.isdigit():
            continue
        for c in _raw_courses(yfile):
            repo = c.get("repo")
            if not repo:
                continue
            ydir = root / repo / yfile.parent.name
            if ydir.is_dir():
                yield str(c["id"]), str(c.get("label") or c["id"]), ydir


def _raw_courses(path: Path) -> list[dict]:
    try:
        raw = yamlio.load(path) or []
    except yamlio.YamlError:
        return []
    return [c for c in raw if isinstance(c, dict) and "id" in c]


def _ask(text: str, data: Path) -> str:
    words = _words(text)
    hits: list[str] = []
    maps: list[str] = []
    for cid, name, ydir in _course_repos(data):
        _, pattern = _sessions_dir(ydir)
        cmap = _course_map(ydir)
        if cmap.is_file():
            maps.append(f"{name}: {cmap}")
            for line in cmap.read_text(encoding="utf-8", errors="replace").splitlines():
                if any(w in line for w in words):
                    hits.append(f"{name} | {line.strip()} | {cmap}")
        for n in range(100):
            sfile = ydir / pattern.format(nn=f"{n:02d}", n=n) / "session.yaml"
            if not sfile.is_file():
                continue
            try:
                title = str(((yamlio.load(sfile) or {}).get("session") or {}).get("title") or "")
            except (yamlio.YamlError, AttributeError):
                continue
            if title and any(w in title for w in words):
                hits.append(f"{name} | 第 {n} 回 | {title} | {sfile}")
    if hits:
        return "\n".join(hits[:_MAX_HITS])
    if maps:
        return "該当なし。探す場所の見当（各授業の course-map.md）:\n" + "\n".join(maps)
    return "該当なし。手元に授業のレポが無い"


def _detached_push(repo: Path) -> None:
    """待たずに push する。

    pull --rebase と push を続けるにはシェルが要るので、ここでは push だけを切り離して走らせる。
    リモートが先に進んでいて拒否されたら静かに失敗し、コミットは手元に残る。
    次に workdesk のセッションが pull --rebase と push をするときに一緒に送られる。
    """
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        subprocess.Popen(["git", "-C", str(repo), "push", "-q"], env=env, **kwargs)
    except OSError:
        pass


def _raise(req: dict, data: Path, now: datetime) -> dict:
    session = req.get("session")
    item = inbox.Item(
        ref=inbox.new_ref(now.date(), req["course"]), verb="raise", course=req["course"],
        cls=req.get("class") if isinstance(req.get("class"), str) else None,
        session=session if isinstance(session, int) and not isinstance(session, bool) else None,
        received=now, no_reply=req.get("no_reply") is True, text=req["text"])
    path = inbox.write(data, item)
    try:
        gitops.commit_paths(data, [f"inbox/{item.ref}.md"], f"inbox: {item.ref}")
    except gitops.GitError:
        path.unlink(missing_ok=True)
        raise
    _detached_push(data)
    return {"protocol": PROTOCOL, "status": "accepted", "ref": item.ref}


def handle(request: dict, data_dir: Path, now: datetime) -> dict:
    if not isinstance(request, dict) or request.get("protocol") != PROTOCOL:
        return dict(_DECLINED)
    verb, course, text = request.get("verb"), request.get("course"), request.get("text")
    if verb not in ("raise", "ask") or not all(isinstance(v, str) and v for v in (course, text)):
        return dict(_DECLINED)
    if verb == "raise":
        return _raise(request, data_dir, now)
    return {"protocol": PROTOCOL, "status": "answered", "answer": _ask(text, data_dir)}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        data = data_dir()
    except ConfigError as e:
        print(str(e), file=sys.stderr)
        return 1
    try:
        request = json.loads(sys.stdin.read())
    except ValueError:
        request = None
    try:
        response = handle(request, data, datetime.now().astimezone())
    except (gitops.GitError, OSError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(response, ensure_ascii=False))
    return 0
