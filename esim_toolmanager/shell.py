from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional, Sequence

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    executed: bool = True

    @property
    def ok(self) -> bool:
        return self.executed and self.returncode == 0

    @property
    def combined(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


class Runner:
    """The only place in the package that spawns a subprocess.

    Keeping it to one class is what makes dry-run and the test fakes possible
    without an `if dry_run:` branch at every call site.
    """

    def which(self, executable: str) -> Optional[str]:
        return shutil.which(executable)

    def run(
        self,
        command: Sequence[str],
        *,
        timeout: int = DEFAULT_TIMEOUT,
        env: Optional[dict[str, str]] = None,
    ) -> CommandResult:
        cmd = tuple(command)
        log.debug("exec: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, **(env or {})},
                check=False,
            )
        except FileNotFoundError:
            return CommandResult(cmd, 127, "", f"{cmd[0]}: not found")
        except subprocess.TimeoutExpired:
            return CommandResult(cmd, 124, "", f"{cmd[0]}: timed out after {timeout}s")
        except OSError as exc:
            return CommandResult(cmd, 126, "", f"{cmd[0]}: {exc}")
        return CommandResult(cmd, proc.returncode, proc.stdout or "", proc.stderr or "")

    def run_mutating(self, command: Sequence[str], **kwargs) -> CommandResult:
        # Separate from run() so a dry run can suppress state-changing commands
        # while still probing versions for real.
        return self.run(command, **kwargs)


class DryRunner(Runner):
    """Records what would have been installed instead of installing it."""

    def __init__(self) -> None:
        self.recorded: list[tuple[str, ...]] = []

    def run_mutating(self, command: Sequence[str], **kwargs) -> CommandResult:
        cmd = tuple(command)
        self.recorded.append(cmd)
        return CommandResult(cmd, 0, "", "", executed=False)


@dataclass
class FakeRunner(Runner):
    """Test double. Returns canned output keyed by command prefix."""

    responses: dict[tuple[str, ...], CommandResult] = field(default_factory=dict)
    available: set[str] = field(default_factory=set)
    calls: list[tuple[str, ...]] = field(default_factory=list)
    default_returncode: int = 127

    def which(self, executable: str) -> Optional[str]:
        return f"/usr/bin/{executable}" if executable in self.available else None

    def run(self, command: Sequence[str], **kwargs) -> CommandResult:
        cmd = tuple(command)
        self.calls.append(cmd)
        if cmd in self.responses:
            return self.responses[cmd]
        # Fall back to a prefix match so tests don't have to spell out flags.
        for key, result in self.responses.items():
            if cmd[: len(key)] == key:
                return result
        return CommandResult(cmd, self.default_returncode, "", "not stubbed")

    def run_mutating(self, command: Sequence[str], **kwargs) -> CommandResult:
        return self.run(command, **kwargs)


def stub(command: Sequence[str], stdout: str = "", returncode: int = 0,
         stderr: str = "") -> tuple[tuple[str, ...], CommandResult]:
    cmd = tuple(command)
    return cmd, CommandResult(cmd, returncode, stdout, stderr)
