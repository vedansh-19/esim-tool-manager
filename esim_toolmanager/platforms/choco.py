from __future__ import annotations

import re
from typing import Optional

from ..models import PackageRef, Version
from ..shell import Runner
from .base import Backend

_LINE = re.compile(r"^(?P<name>\S+)\s+(?P<version>\d[\w.\-]*)\s*$", re.MULTILINE)


class ChocoBackend(Backend):
    name = "choco"
    label = "Chocolatey (Windows)"
    platforms = ("win32", "cygwin")
    elevates = True
    executable = "choco"

    def install_command(self, ref: PackageRef) -> tuple[str, ...]:
        return ("choco", "install", ref.package, "-y")

    def _lookup(self, ref: PackageRef, runner: Runner, local: bool) -> Optional[Version]:
        cmd = ["choco", "list", ref.package, "--exact", "--limit-output"]
        if local:
            cmd.append("--local-only")
        result = runner.run(cmd, timeout=60)
        if not result.ok:
            return None
        for match in _LINE.finditer(result.combined):
            if match.group("name").lower() == ref.package.lower():
                return Version.parse(match.group("version"))
        return None

    def query_installed(self, ref: PackageRef, runner: Runner) -> Optional[Version]:
        return self._lookup(ref, runner, local=True)

    def query_candidate(self, ref: PackageRef, runner: Runner) -> Optional[Version]:
        return self._lookup(ref, runner, local=False)
