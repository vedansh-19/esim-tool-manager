from __future__ import annotations

import json
import logging
import logging.handlers
import os
import platform
import sys
import time
from pathlib import Path
from typing import Optional

from .models import ActionOutcome

AUDIT_FILENAME = "actions.jsonl"
HUMAN_FILENAME = "toolmanager.log"


def default_log_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "esim-toolmanager"
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "esim-toolmanager" / "logs"
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "esim-toolmanager"


def configure_logging(verbosity: int = 0, log_dir: Optional[Path] = None) -> Path:
    directory = log_dir or default_log_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        directory = Path()

    root = logging.getLogger("esim_toolmanager")
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stderr)
    console.setLevel({0: logging.WARNING, 1: logging.INFO}.get(verbosity, logging.DEBUG))
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(console)

    if directory != Path():
        handler = logging.handlers.RotatingFileHandler(
            directory / HUMAN_FILENAME, maxBytes=1_000_000, backupCount=3,
            encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(handler)

    return directory


class AuditLog:
    """Append-only JSONL record of every state-changing command.

    Kept separate from the human log so free-text formatting can never corrupt
    the machine-readable one. If the directory isn't writable it quietly turns
    itself off -- logging must never be the reason a run fails.
    """

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = directory or default_log_dir()
        self.path = self.directory / AUDIT_FILENAME
        self._enabled = True
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._enabled = False

    def _write(self, record: dict) -> None:
        if not self._enabled:
            return
        record["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except OSError:
            self._enabled = False

    def session_start(self, command: str, backend: Optional[str]) -> None:
        self._write({
            "event": "session_start",
            "command": command,
            "backend": backend,
            "platform": platform.platform(),
            "python": platform.python_version(),
        })

    def record(self, outcome: ActionOutcome) -> None:
        self._write({
            "event": "action",
            "tool": outcome.action.tool,
            "backend": outcome.action.backend,
            "command": list(outcome.action.command),
            "reason": outcome.action.reason,
            "executed": outcome.executed,
            "succeeded": outcome.succeeded,
            "returncode": outcome.returncode,
            "message": outcome.message,
        })

    def session_end(self, succeeded: int, failed: int) -> None:
        self._write({"event": "session_end", "succeeded": succeeded, "failed": failed})

    def tail(self, limit: int = 20) -> list[dict]:
        if not self.path.is_file():
            return []
        try:
            lines = self.path.read_text("utf-8").strip().splitlines()
        except OSError:
            return []
        records = []
        for line in lines[-limit:]:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records
