from __future__ import annotations

import json
from typing import Optional

from ..models import PackageRef, Version
from ..shell import Runner
from .base import Backend


class BrewBackend(Backend):
    name = "brew"
    label = "Homebrew (macOS)"
    platforms = ("darwin",)
    elevates = False
    executable = "brew"

    def install_command(self, ref: PackageRef) -> tuple[str, ...]:
        if ref.cask:
            return ("brew", "install", "--cask", ref.package)
        return ("brew", "install", ref.package)

    def _info(self, ref: PackageRef, runner: Runner) -> Optional[dict]:
        cmd = ["brew", "info", "--json=v2"]
        if ref.cask:
            cmd.append("--cask")
        cmd.append(ref.package)
        # NO_AUTO_UPDATE, otherwise a plain `brew info` can sit there updating
        # taps for a minute before answering.
        result = runner.run(cmd, timeout=60, env={"HOMEBREW_NO_AUTO_UPDATE": "1"})
        if not result.ok:
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        entries = payload.get("casks" if ref.cask else "formulae") or []
        return entries[0] if entries else None

    def query_installed(self, ref: PackageRef, runner: Runner) -> Optional[Version]:
        info = self._info(ref, runner)
        if info is None:
            return None
        if ref.cask:
            installed = info.get("installed")
            return Version.parse(installed) if isinstance(installed, str) else None
        entries = info.get("installed") or []
        if not entries:
            return None
        return Version.parse(entries[0].get("version", ""))

    def query_candidate(self, ref: PackageRef, runner: Runner) -> Optional[Version]:
        info = self._info(ref, runner)
        if info is None:
            return None
        if ref.cask:
            return Version.parse(str(info.get("version", "")))
        stable = (info.get("versions") or {}).get("stable")
        return Version.parse(stable) if stable else None
