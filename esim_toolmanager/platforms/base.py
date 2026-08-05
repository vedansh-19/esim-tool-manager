from __future__ import annotations

import abc
import os
from typing import Optional

from ..models import PackageRef, Version
from ..shell import CommandResult, Runner


class Backend(abc.ABC):
    """A package manager. Builds commands; never runs them itself."""

    name: str = ""

    label: str = ""

    platforms: tuple[str, ...] = ()

    # Whether this package manager normally needs root/Administrator.
    elevates: bool = False

    executable: str = ""

    def __init__(self, *, elevated: Optional[bool] = None) -> None:
        self._elevated = elevated

    @property
    def is_elevated(self) -> bool:
        if self._elevated is not None:
            return self._elevated
        geteuid = getattr(os, "geteuid", None)
        return geteuid() == 0 if geteuid is not None else False

    @property
    def requires_privilege(self) -> bool:
        return self.elevates and not self.is_elevated

    def privilege_prefix(self) -> tuple[str, ...]:
        # Empty when we are already root. Docker images and CI runners often
        # run as root and ship no sudo binary at all, so prefixing it
        # unconditionally makes the install fail with "sudo: not found".
        return ("sudo",) if self.requires_privilege else ()

    def is_available(self, runner: Runner) -> bool:
        return runner.which(self.executable) is not None

    @abc.abstractmethod
    def install_command(self, ref: PackageRef) -> tuple[str, ...]:
        ...

    @abc.abstractmethod
    def query_installed(self, ref: PackageRef, runner: Runner) -> Optional[Version]:
        ...

    @abc.abstractmethod
    def query_candidate(self, ref: PackageRef, runner: Runner) -> Optional[Version]:
        ...

    @staticmethod
    def _first_version(result: CommandResult) -> Optional[Version]:
        return Version.parse(result.combined) if result.ok else None

    def describe_unavailable(self) -> str:
        return f"{self.label} is not installed on this system"

    def __repr__(self) -> str:
        return f"<Backend {self.name}>"
