from __future__ import annotations

import logging
from typing import Iterable, Optional, Sequence

from .detect import detect_tool
from .models import ActionOutcome, Detection, PlannedAction, Status, ToolSpec
from .platforms.base import Backend
from .shell import DryRunner, Runner

log = logging.getLogger(__name__)

INSTALL_TIMEOUT = 1800


class InstallError(RuntimeError):
    pass


def plan_installs(
    detections: Sequence[Detection],
    backend: Backend,
    *,
    include_outdated: bool = True,
    reinstall: bool = False,
) -> tuple[list[PlannedAction], list[tuple[ToolSpec, str]]]:
    actions: list[PlannedAction] = []
    skipped: list[tuple[ToolSpec, str]] = []

    for det in detections:
        tool = det.tool

        if det.status is Status.OK and not reinstall:
            skipped.append((tool, f"already satisfied ({det.version})"))
            continue
        if det.status is Status.OUTDATED and not include_outdated and not reinstall:
            skipped.append((tool, f"present but outdated ({det.version}); not selected"))
            continue
        # A tool whose version we can't read is probably working. Overwriting
        # it is worse than leaving it alone, so that needs --reinstall.
        if det.status is Status.UNKNOWN_VERSION and not reinstall:
            skipped.append((
                tool,
                "present but its version could not be read; not touching a working "
                "installation (use --reinstall to force)",
            ))
            continue

        ref = tool.package_for(backend.name)
        if ref is None:
            skipped.append((tool, f"no {backend.label} package recorded"))
            continue
        if not ref.installable:
            skipped.append((tool, ref.note or f"not installable via {backend.label}"))
            continue

        actions.append(PlannedAction(
            tool=tool.name,
            backend=backend.name,
            command=backend.install_command(ref),
            reason=_reason_for(det),
            requires_privilege=backend.requires_privilege,
        ))

    return actions, skipped


def _reason_for(det: Detection) -> str:
    if det.status is Status.MISSING:
        return "not installed"
    if det.status is Status.OUTDATED:
        return f"installed {det.version}, requires {det.tool.constraint.describe()}"
    if det.status is Status.UNKNOWN_VERSION:
        return "version unreadable; reinstall requested"
    return "reinstall requested"


def execute_plan(
    actions: Iterable[PlannedAction],
    runner: Runner,
    registry_lookup,
    *,
    backend: Optional[Backend] = None,
    verify: bool = True,
    stop_on_error: bool = False,
) -> list[ActionOutcome]:
    outcomes: list[ActionOutcome] = []
    dry = isinstance(runner, DryRunner)

    for action in actions:
        log.info("installing %s: %s", action.tool, " ".join(action.command))
        result = runner.run_mutating(
            list(action.command),
            timeout=INSTALL_TIMEOUT,
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )

        outcome = ActionOutcome(
            action=action,
            executed=result.executed,
            succeeded=result.ok,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            message="planned (dry run)" if dry else "",
        )

        if dry:
            outcomes.append(outcome)
            continue

        if not result.ok:
            outcome.message = _explain_failure(action, result.returncode, result.combined)
            outcomes.append(outcome)
            if stop_on_error:
                break
            continue

        # Exit code 0 from a package manager means "unpacked", not "runs".
        # A Homebrew cask can install KiCad while kicad-cli stays off PATH.
        if verify:
            tool = registry_lookup(action.tool)
            check = detect_tool(tool, runner, backend)
            if check.status is Status.OK:
                outcome.message = f"installed and verified ({check.version})"
            elif check.found:
                outcome.succeeded = False
                outcome.message = (
                    f"{action.backend} reported success, but the tool still does not "
                    f"satisfy its requirement: {check.detail}"
                )
            else:
                outcome.succeeded = False
                outcome.message = (
                    f"{action.backend} reported success, but "
                    f"'{tool.probe.executable}' is still not on PATH -- the package "
                    f"may install to a location that needs PATH setup"
                )
        else:
            outcome.message = "installed (not verified)"

        outcomes.append(outcome)

    return outcomes


def _explain_failure(action: PlannedAction, code: Optional[int], output: str) -> str:
    text = output.lower()
    if code == 127:
        # Name the executable that was actually missing. Blaming the backend
        # here sends people to debug apt when the real problem was sudo.
        missing = action.command[0] if action.command else action.backend
        hint = ""
        if missing == "sudo":
            hint = (" -- this process is not root and sudo is unavailable; "
                    "run as root or install sudo")
        return f"'{missing}' is not installed or not on PATH{hint}"
    if action.requires_privilege and ("permission denied" in text or "are you root" in text):
        return "insufficient privileges -- re-run with sudo, or as Administrator"
    if "unable to locate package" in text or "no available formula" in text:
        return ("the package name in the registry is not valid for this system's "
                "sources; update registry/tools.json")
    if "could not get lock" in text:
        return "another package manager process is running; wait for it to finish"
    if code == 124:
        return "timed out -- the download may be stalled; check network access"
    first = output.strip().splitlines()[0] if output.strip() else ""
    return f"install failed (exit {code}){': ' + first if first else ''}"
