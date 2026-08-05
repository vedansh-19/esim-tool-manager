from __future__ import annotations

import os
import sys
from typing import Sequence

from .models import ActionOutcome, Criticality, Detection, PlannedAction, Status

_STATUS_TEXT = {
    Status.OK: "OK",
    Status.OUTDATED: "OUTDATED",
    Status.MISSING: "MISSING",
    Status.UNKNOWN_VERSION: "UNKNOWN",
}

_STATUS_COLOR = {
    Status.OK: "32",
    Status.OUTDATED: "33",
    Status.MISSING: "31",
    Status.UNKNOWN_VERSION: "36",
}

_CRITICALITY_MARK = {
    Criticality.REQUIRED: "!",
    Criticality.RECOMMENDED: "+",
    Criticality.OPTIONAL: " ",
}


def use_colour(stream=None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    stream = stream or sys.stdout
    return hasattr(stream, "isatty") and stream.isatty()


def _paint(text: str, code: str, enabled: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if enabled else text


def render_detections(detections: Sequence[Detection], *, colour: bool = False,
                      verbose: bool = False) -> str:
    if not detections:
        return "No tools selected."

    rows = []
    for det in detections:
        rows.append((
            _CRITICALITY_MARK[det.tool.criticality],
            det.tool.name,
            str(det.version) if det.version else "-",
            det.tool.constraint.describe(),
            _STATUS_TEXT[det.status],
            det,
        ))

    # Hand-rolled column widths; a table library would be a dependency, and the
    # whole point of this project is not needing any.
    w_name = max(len("TOOL"), *(len(r[1]) for r in rows))
    w_found = max(len("FOUND"), *(len(r[2]) for r in rows))
    w_req = max(len("REQUIRED"), *(len(r[3]) for r in rows))

    header = f"  {'TOOL':<{w_name}}  {'FOUND':<{w_found}}  {'REQUIRED':<{w_req}}  STATUS"
    lines = [header, "  " + "-" * (len(header) - 2)]

    for mark, name, found, req, status_text, det in rows:
        painted = _paint(status_text, _STATUS_COLOR[det.status], colour)
        lines.append(f"{mark} {name:<{w_name}}  {found:<{w_found}}  {req:<{w_req}}  {painted}")
        if verbose or det.status is not Status.OK:
            lines.append(f"  {'':<{w_name}}  └─ {det.detail}")

    lines.append("")
    lines.append(summary_line(detections, colour=colour))
    lines.append("  legend: ! required   + recommended   (blank) optional")
    return "\n".join(lines)


def summary_line(detections: Sequence[Detection], *, colour: bool = False) -> str:
    total = len(detections)
    ok = sum(1 for d in detections if d.status is Status.OK)
    blocking = [d for d in detections if d.blocking]

    parts = [f"{ok}/{total} satisfied"]
    for status in (Status.OUTDATED, Status.MISSING, Status.UNKNOWN_VERSION):
        count = sum(1 for d in detections if d.status is status)
        if count:
            parts.append(f"{count} {_STATUS_TEXT[status].lower()}")

    text = "  " + ", ".join(parts)
    if blocking:
        names = ", ".join(d.tool.name for d in blocking)
        text += _paint(f"\n  eSim cannot run without: {names}", "31", colour)
    return text


def render_plan(actions: Sequence[PlannedAction],
                skipped: Sequence[tuple] = (), *, colour: bool = False) -> str:
    lines: list[str] = []

    if actions:
        needs_priv = any(a.requires_privilege for a in actions)
        lines.append(f"  Planned actions ({len(actions)}):")
        for i, action in enumerate(actions, 1):
            lines.append(f"    {i}. {action.tool} -- {action.reason}")
            lines.append(f"       $ {' '.join(action.command)}")
        if needs_priv:
            lines.append("")
            lines.append(_paint("  Note: these commands require administrator "
                                "privileges.", "33", colour))
    else:
        lines.append("  Nothing to install.")

    if skipped:
        lines.append("")
        lines.append(f"  Skipped ({len(skipped)}):")
        for tool, reason in skipped:
            lines.append(f"    - {tool.name}: {reason}")

    return "\n".join(lines)


def render_outcomes(outcomes: Sequence[ActionOutcome], *, colour: bool = False) -> str:
    if not outcomes:
        return "  No actions were performed."

    lines = []
    for outcome in outcomes:
        if not outcome.executed:
            mark, code = "DRY", "36"
        elif outcome.succeeded:
            mark, code = "OK", "32"
        else:
            mark, code = "FAIL", "31"
        lines.append(f"  [{_paint(mark, code, colour)}] {outcome.action.tool}: "
                     f"{outcome.message}")
        if not outcome.succeeded and outcome.executed and outcome.stderr.strip():
            first = outcome.stderr.strip().splitlines()[0]
            lines.append(f"         {first}")

    failed = sum(1 for o in outcomes if o.executed and not o.succeeded)
    done = sum(1 for o in outcomes if o.executed and o.succeeded)
    lines.append("")
    lines.append(f"  {done} succeeded, {failed} failed, {len(outcomes)} total")
    return "\n".join(lines)


def render_tool_detail(det: Detection) -> str:
    tool = det.tool
    lines = [
        f"  {tool.name} -- {tool.summary}",
        f"    criticality : {tool.criticality.value}",
        f"    status      : {_STATUS_TEXT[det.status]}",
        f"    found       : {det.version if det.version else 'not found'}",
        f"    requires    : {tool.constraint.describe()} "
        f"(source: {tool.constraint.source})",
        f"    path        : {det.path or '-'}",
    ]
    if tool.used_by:
        lines.append(f"    used by     : {', '.join(tool.used_by)}")
    if tool.homepage:
        lines.append(f"    homepage    : {tool.homepage}")
    lines.append("    packages    :")
    for backend, ref in sorted(tool.packages.items()):
        if ref.installable:
            suffix = " (cask)" if ref.cask else ""
            lines.append(f"      {backend:<6} {ref.package}{suffix}")
        else:
            lines.append(f"      {backend:<6} - {ref.note or 'unavailable'}")
    if det.detail:
        lines.append(f"    detail      : {det.detail}")
    return "\n".join(lines)
