from __future__ import annotations

import re
from typing import Optional

from ..models import PackageRef, Version
from ..shell import Runner
from .base import Backend

_INSTALLED = re.compile(r"^\s*Installed:\s*(.+)$", re.MULTILINE)
_CANDIDATE = re.compile(r"^\s*Candidate:\s*(.+)$", re.MULTILINE)


class AptBackend(Backend):
    name = "apt"
    label = "APT (Debian/Ubuntu)"
    platforms = ("linux",)
    elevates = True
    executable = "apt-get"

    def install_command(self, ref: PackageRef) -> tuple[str, ...]:
        return (*self.privilege_prefix(), "apt-get", "install", "-y", ref.package)

    def _policy(self, ref: PackageRef, runner: Runner) -> str:
        result = runner.run(["apt-cache", "policy", ref.package], timeout=30)
        return result.combined if result.ok else ""

    def query_installed(self, ref: PackageRef, runner: Runner) -> Optional[Version]:
        return self._extract(self._policy(ref, runner), _INSTALLED)

    def query_candidate(self, ref: PackageRef, runner: Runner) -> Optional[Version]:
        return self._extract(self._policy(ref, runner), _CANDIDATE)

    @staticmethod
    def _extract(text: str, pattern: re.Pattern[str]) -> Optional[Version]:
        match = pattern.search(text)
        if match is None:
            return None
        value = match.group(1).strip()
        if value.startswith("(none)"):
            return None
        # Strip the Debian epoch ("1:8.0.4"); it's packaging metadata, not part
        # of the upstream version we're comparing against.
        value = value.split(":", 1)[-1] if re.match(r"^\d+:", value) else value
        return Version.parse(value)
