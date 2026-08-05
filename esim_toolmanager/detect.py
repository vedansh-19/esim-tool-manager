from __future__ import annotations

import logging
import re
from typing import Iterable, Optional

from .models import Detection, ProbeSpec, Status, ToolSpec, Version
from .platforms.base import Backend
from .shell import Runner

log = logging.getLogger(__name__)

PROBE_TIMEOUT = 20


def probe_version(probe: ProbeSpec, runner: Runner) -> tuple[Optional[Version], str]:
    result = runner.run([probe.executable, *probe.args], timeout=PROBE_TIMEOUT)
    text = result.combined if probe.merge_stderr else result.stdout

    if not text.strip():
        return None, ""

    if probe.pattern:
        match = re.search(probe.pattern, text)
        if match:
            return Version.parse(match.group(1)), text
        log.debug("pattern %r did not match output of %s", probe.pattern, probe.executable)
        return None, text

    return Version.parse(text), text


def detect_tool(
    tool: ToolSpec,
    runner: Runner,
    backend: Optional[Backend] = None,
) -> Detection:
    """Work out one tool's status by running it, not by asking apt/brew.

    eSim's NGHDL workflow has users build Ngspice and GHDL from source, and on
    those machines dpkg reports the tool as absent. Asking the binary itself
    can't make that mistake.
    """
    path = runner.which(tool.probe.executable)

    if path is None:
        detail = _missing_detail(tool, backend)
        return Detection(tool=tool, found=False, path=None, version=None,
                         status=Status.MISSING, detail=detail)

    version, raw = probe_version(tool.probe, runner)

    if version is None:
        # The tool is there but wouldn't tell us its version. Ask the package
        # database as a fallback before giving up.
        version = _package_version(tool, backend, runner)
        if version is None:
            first_line = raw.strip().splitlines()[0] if raw.strip() else "no output"
            return Detection(
                tool=tool, found=True, path=path, version=None,
                status=Status.UNKNOWN_VERSION,
                detail=f"installed at {path}, but the version could not be parsed "
                       f"({first_line!r})",
            )

    if tool.constraint.is_empty or tool.constraint.permits(version):
        return Detection(tool=tool, found=True, path=path, version=version,
                         status=Status.OK, detail=f"{path}")

    return Detection(
        tool=tool, found=True, path=path, version=version, status=Status.OUTDATED,
        detail=f"found {version}, requires {tool.constraint.describe()} "
               f"(source: {tool.constraint.source})",
    )


def detect_all(
    tools: Iterable[ToolSpec],
    runner: Runner,
    backend: Optional[Backend] = None,
) -> list[Detection]:
    return [detect_tool(tool, runner, backend) for tool in tools]


def _package_version(tool: ToolSpec, backend: Optional[Backend],
                     runner: Runner) -> Optional[Version]:
    if backend is None:
        return None
    ref = tool.package_for(backend.name)
    if ref is None or not ref.installable:
        return None
    try:
        return backend.query_installed(ref, runner)
    except Exception as exc:
        log.debug("package query failed for %s: %s", tool.name, exc)
        return None


def _missing_detail(tool: ToolSpec, backend: Optional[Backend]) -> str:
    if backend is None:
        return f"'{tool.probe.executable}' not found on PATH"

    ref = tool.package_for(backend.name)
    if ref is None:
        return (f"'{tool.probe.executable}' not found; no {backend.label} package "
                f"is recorded for this tool")
    if not ref.installable:
        note = ref.note or "no package available for this backend"
        return f"'{tool.probe.executable}' not found; {note}"
    return f"'{tool.probe.executable}' not found; installable as {backend.name}:{ref.package}"
