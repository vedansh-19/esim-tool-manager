from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .auditlog import AuditLog, configure_logging
from .detect import detect_all
from .installer import execute_plan, plan_installs
from .models import Detection, Status
from .platforms import ALL_BACKENDS, select_backend
from .registry import Registry, RegistryError
from .report import (render_detections, render_outcomes, render_plan,
                     render_tool_detail, use_colour)
from .shell import DryRunner, Runner

# Distinct codes so `toolman check` is usable in a provisioning script:
# 1 means eSim genuinely won't run, 2 means only optional things are missing.
EXIT_OK = 0
EXIT_BLOCKING = 1
EXIT_WARN = 2
EXIT_USAGE = 3

PROG = "toolman"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Automated tool manager for eSim's external dependencies.",
        epilog="Run '%(prog)s <command> --help' for command-specific options.",
    )
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="increase log verbosity (repeatable)")
    parser.add_argument("--registry", type=Path, metavar="PATH",
                        help="use an alternative tools.json")
    parser.add_argument("--backend", choices=[b.name for b in ALL_BACKENDS],
                        help="force a packaging backend instead of auto-detecting")
    parser.add_argument("--log-dir", type=Path, metavar="PATH",
                        help="directory for the human and audit logs")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_check = sub.add_parser("check", help="report the status of each tool")
    p_check.add_argument("tools", nargs="*", help="limit to these tools")
    p_check.add_argument("--json", action="store_true", help="machine-readable output")
    p_check.add_argument("--required-only", action="store_true",
                         help="consider only tools eSim cannot run without")

    p_install = sub.add_parser("install", help="install missing or outdated tools")
    p_install.add_argument("tools", nargs="*", help="limit to these tools")
    p_install.add_argument("--dry-run", action="store_true",
                           help="show the exact commands without running them")
    p_install.add_argument("--yes", "-y", action="store_true",
                           help="do not prompt for confirmation")
    p_install.add_argument("--reinstall", action="store_true",
                           help="install even when the tool is already satisfied")
    p_install.add_argument("--skip-outdated", action="store_true",
                           help="install only missing tools, leave outdated ones alone")
    p_install.add_argument("--no-verify", action="store_true",
                           help="skip the post-install re-probe")

    p_list = sub.add_parser("list", help="list the tools in the registry")
    p_list.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="show everything known about one tool")
    p_show.add_argument("tool")

    p_log = sub.add_parser("log", help="show recent actions from the audit log")
    p_log.add_argument("-n", "--lines", type=int, default=20)
    p_log.add_argument("--json", action="store_true")

    return parser


def _load_registry(args) -> Registry:
    return Registry.load(args.registry)


def _resolve_backend(args, runner: Runner):
    backend, explanation = select_backend(runner, override=args.backend)
    return backend, explanation


def _exit_code_for(detections: Sequence[Detection]) -> int:
    if any(d.blocking for d in detections):
        return EXIT_BLOCKING
    if any(d.status is not Status.OK for d in detections):
        return EXIT_WARN
    return EXIT_OK


def cmd_check(args, registry: Registry, runner: Runner) -> int:
    backend, explanation = _resolve_backend(args, runner)
    tools = registry.select(args.tools)
    if args.required_only:
        tools = tuple(t for t in tools if t.criticality.value == "required")

    detections = detect_all(tools, runner, backend)

    if args.json:
        print(json.dumps({
            "backend": backend.name if backend else None,
            "backend_detail": explanation,
            "tools": [_detection_json(d) for d in detections],
        }, indent=2))
        return _exit_code_for(detections)

    print(f"\n  Packaging backend: {explanation}\n")
    print(render_detections(detections, colour=use_colour(), verbose=args.verbose > 0))
    print()
    return _exit_code_for(detections)


def cmd_install(args, registry: Registry, runner: Runner) -> int:
    backend, explanation = _resolve_backend(args, runner)
    if backend is None:
        print(f"  Cannot install: {explanation}", file=sys.stderr)
        return EXIT_USAGE

    audit = AuditLog(args.log_dir)
    audit.session_start("install", backend.name)

    tools = registry.select(args.tools)
    detections = detect_all(tools, runner, backend)
    actions, skipped = plan_installs(
        detections, backend,
        include_outdated=not args.skip_outdated,
        reinstall=args.reinstall,
    )

    print(f"\n  Packaging backend: {explanation}\n")
    print(render_plan(actions, skipped, colour=use_colour()))
    print()

    if not actions:
        audit.session_end(0, 0)
        return _exit_code_for(detections)

    # Swap the runner rather than branching inside execute_plan, so a dry run
    # goes down exactly the same code path as a real one.
    if args.dry_run:
        runner = DryRunner()
    elif not args.yes and sys.stdin.isatty():
        answer = input("  Proceed? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("  Aborted.")
            audit.session_end(0, 0)
            return EXIT_WARN
        print()

    outcomes = execute_plan(
        actions, runner, registry.get,
        backend=backend, verify=not args.no_verify,
    )
    for outcome in outcomes:
        audit.record(outcome)

    print(render_outcomes(outcomes, colour=use_colour()))
    print()

    succeeded = sum(1 for o in outcomes if o.executed and o.succeeded)
    failed = sum(1 for o in outcomes if o.executed and not o.succeeded)
    audit.session_end(succeeded, failed)

    if args.dry_run:
        return EXIT_OK
    if failed:
        return EXIT_BLOCKING
    return _exit_code_for(detect_all(tools, runner, backend))


def cmd_list(args, registry: Registry, runner: Runner) -> int:
    if args.json:
        print(json.dumps({
            "meta": registry.meta,
            "tools": {
                t.name: {
                    "summary": t.summary,
                    "criticality": t.criticality.value,
                    "requires": t.constraint.describe(),
                    "constraint_source": t.constraint.source,
                    "used_by": list(t.used_by),
                    "packages": {b: r.package or None for b, r in t.packages.items()},
                }
                for t in registry
            },
        }, indent=2))
        return EXIT_OK

    target = registry.meta.get("target", "eSim")
    print(f"\n  {len(registry)} tools registered for {target}:\n")
    width = max(len(t.name) for t in registry)
    for tool in registry:
        mark = {"required": "!", "recommended": "+", "optional": " "}[tool.criticality.value]
        print(f"  {mark} {tool.name:<{width}}  {tool.summary}")
    print("\n  legend: ! required   + recommended   (blank) optional\n")
    return EXIT_OK


def cmd_show(args, registry: Registry, runner: Runner) -> int:
    backend, _ = _resolve_backend(args, runner)
    tool = registry.get(args.tool)
    detection = detect_all([tool], runner, backend)[0]
    print()
    print(render_tool_detail(detection))
    print()
    return EXIT_OK


def cmd_log(args, registry: Registry, runner: Runner) -> int:
    audit = AuditLog(args.log_dir)
    records = audit.tail(args.lines)
    if args.json:
        print(json.dumps(records, indent=2))
        return EXIT_OK
    if not records:
        print(f"\n  No actions recorded yet ({audit.path})\n")
        return EXIT_OK
    print(f"\n  Last {len(records)} entries from {audit.path}:\n")
    for rec in records:
        stamp = rec.get("timestamp", "")
        event = rec.get("event")
        if event == "action":
            status = "ok" if rec.get("succeeded") else "FAILED"
            if not rec.get("executed"):
                status = "dry-run"
            print(f"  {stamp}  {rec.get('tool'):<12} {status:<8} "
                  f"{' '.join(rec.get('command', []))}")
        else:
            print(f"  {stamp}  [{event}] "
                  + " ".join(f"{k}={v}" for k, v in rec.items()
                             if k not in {"timestamp", "event"}))
    print()
    return EXIT_OK


def _detection_json(det: Detection) -> dict:
    return {
        "name": det.tool.name,
        "criticality": det.tool.criticality.value,
        "status": det.status.value,
        "found_version": str(det.version) if det.version else None,
        "required": det.tool.constraint.describe(),
        "constraint_source": det.tool.constraint.source,
        "path": det.path,
        "blocking": det.blocking,
        "detail": det.detail,
    }


COMMANDS = {
    "check": cmd_check,
    "install": cmd_install,
    "list": cmd_list,
    "show": cmd_show,
    "log": cmd_log,
}


def main(argv: Optional[Sequence[str]] = None, runner: Optional[Runner] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return EXIT_USAGE

    configure_logging(args.verbose, args.log_dir)
    runner = runner or Runner()

    try:
        registry = _load_registry(args)
    except RegistryError as exc:
        print(f"  Registry error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        return COMMANDS[args.command](args, registry, runner)
    except RegistryError as exc:
        print(f"  {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\n  Interrupted.", file=sys.stderr)
        return EXIT_WARN


if __name__ == "__main__":
    sys.exit(main())
