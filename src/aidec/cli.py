"""aidec コマンドの入口と、各サブコマンドの共通部分。"""
from __future__ import annotations

import importlib
import sys

from classdays.calendar import CalendarError
from classdays.plan import PlanError

from .config import ConfigError
from .data import DataError
from .gitops import GitError
from .schedule import ScheduleError

KNOWN_ERRORS = (CalendarError, PlanError, ConfigError, DataError, GitError, ScheduleError)


def setup_console() -> None:
    """Windows でパイプに出したときも UTF-8 で書く。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def error(message: str) -> None:
    print(message, file=sys.stderr)


# サブコマンド名 -> main(argv) を持つモジュール。循環 import を避けるため、呼ぶときに読む。
COMMANDS = {"issue": "aidec.issue", "week": "aidec.week", "check": "aidec.check"}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in COMMANDS:
        print(f"usage: aidec {{{'|'.join(COMMANDS)}}} ...", file=sys.stderr)
        return 2
    return importlib.import_module(COMMANDS[argv[0]]).main(argv[1:])
