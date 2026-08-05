from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional


_VERSION_TOKEN = re.compile(r"(\d+(?:\.\d+)*)")


@dataclass(frozen=True, order=False)
class Version:
    """A numeric version, plus the original string it was parsed from."""

    raw: str
    parts: tuple[int, ...] = field(default_factory=tuple)

    @classmethod
    def parse(cls, text: str) -> Optional["Version"]:
        if not text:
            return None
        match = _VERSION_TOKEN.search(text)
        if match is None:
            return None
        parts = tuple(int(p) for p in match.group(1).split("."))
        return cls(raw=text.strip(), parts=parts)

    @staticmethod
    def _align(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
        # Pad with zeros so "42" and "42.0.0" compare equal.
        width = max(len(a), len(b))
        return a + (0,) * (width - len(a)), b + (0,) * (width - len(b))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        x, y = self._align(self.parts, other.parts)
        return x == y

    def __lt__(self, other: "Version") -> bool:
        x, y = self._align(self.parts, other.parts)
        return x < y

    def __le__(self, other: "Version") -> bool:
        return self < other or self == other

    def __gt__(self, other: "Version") -> bool:
        return not self <= other

    def __ge__(self, other: "Version") -> bool:
        return not self < other

    def __hash__(self) -> int:
        return hash(self.parts)

    def __str__(self) -> str:
        return ".".join(str(p) for p in self.parts) if self.parts else self.raw


@dataclass(frozen=True)
class VersionConstraint:
    """Version window for a tool. `source` records where the bound came from."""

    minimum: Optional[Version] = None
    maximum: Optional[Version] = None
    exact: Optional[Version] = None
    source: str = "assumed"

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "VersionConstraint":
        if not data:
            return cls()
        parse = lambda k: Version.parse(data[k]) if data.get(k) else None
        return cls(
            minimum=parse("min"),
            maximum=parse("max"),
            exact=parse("exact"),
            source=data.get("source", "assumed"),
        )

    @property
    def is_empty(self) -> bool:
        return self.minimum is None and self.maximum is None and self.exact is None

    def permits(self, version: Optional[Version]) -> bool:
        if version is None:
            return False
        if self.exact is not None:
            return version == self.exact
        if self.minimum is not None and version < self.minimum:
            return False
        if self.maximum is not None and version > self.maximum:
            return False
        return True

    def describe(self) -> str:
        if self.exact is not None:
            return f"== {self.exact}"
        bounds = []
        if self.minimum is not None:
            bounds.append(f">= {self.minimum}")
        if self.maximum is not None:
            bounds.append(f"<= {self.maximum}")
        return ", ".join(bounds) if bounds else "any"


class Criticality(str, Enum):
    """How badly eSim needs a tool. Drives the process exit code."""

    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class PackageRef:
    """One tool's package name for one backend.

    An empty `package` with a `note` means "exists, but you can't install it
    this way" -- e.g. Ngspice on Windows, which ships inside eSim's installer.
    """

    backend: str
    package: str
    cask: bool = False
    note: str = ""

    @classmethod
    def from_dict(cls, backend: str, data: object) -> "PackageRef":
        if isinstance(data, str):
            return cls(backend=backend, package=data)
        assert isinstance(data, dict)
        return cls(
            backend=backend,
            package=data.get("package", ""),
            cask=bool(data.get("cask", False)),
            note=data.get("note", ""),
        )

    @property
    def installable(self) -> bool:
        return bool(self.package)


@dataclass(frozen=True)
class ProbeSpec:
    """How to ask one tool for its version.

    merge_stderr defaults to True because a lot of these tools print their
    banner to stderr rather than stdout.
    """

    executable: str
    args: tuple[str, ...] = ("--version",)
    pattern: Optional[str] = None
    merge_stderr: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "ProbeSpec":
        return cls(
            executable=data["executable"],
            args=tuple(data.get("args", ["--version"])),
            pattern=data.get("pattern"),
            merge_stderr=bool(data.get("merge_stderr", True)),
        )


@dataclass(frozen=True)
class ToolSpec:
    """One entry from registry/tools.json, parsed."""

    name: str
    summary: str
    criticality: Criticality
    probe: ProbeSpec
    constraint: VersionConstraint
    packages: dict[str, PackageRef]
    used_by: tuple[str, ...] = ()
    homepage: str = ""

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "ToolSpec":
        packages = {
            backend: PackageRef.from_dict(backend, ref)
            for backend, ref in (data.get("packages") or {}).items()
        }
        return cls(
            name=name,
            summary=data.get("summary", ""),
            criticality=Criticality(data.get("criticality", "required")),
            probe=ProbeSpec.from_dict(data["probe"]),
            constraint=VersionConstraint.from_dict(data.get("version")),
            packages=packages,
            used_by=tuple(data.get("used_by", ())),
            homepage=data.get("homepage", ""),
        )

    def package_for(self, backend: str) -> Optional[PackageRef]:
        return self.packages.get(backend)


class Status(str, Enum):
    OK = "ok"
    OUTDATED = "outdated"
    MISSING = "missing"
    UNKNOWN_VERSION = "unknown"


@dataclass(frozen=True)
class Detection:
    """What we found on this machine for one tool."""

    tool: ToolSpec
    found: bool
    path: Optional[str]
    version: Optional[Version]
    status: Status
    detail: str = ""

    @property
    def satisfied(self) -> bool:
        return self.status is Status.OK

    @property
    def blocking(self) -> bool:
        return self.criticality_is_required and not self.satisfied

    @property
    def criticality_is_required(self) -> bool:
        return self.tool.criticality is Criticality.REQUIRED


@dataclass(frozen=True)
class PlannedAction:
    """An install command we intend to run, before we decide to run it."""

    tool: str
    backend: str
    command: tuple[str, ...]
    reason: str
    requires_privilege: bool = False


@dataclass
class ActionOutcome:
    """What actually happened when we ran a PlannedAction."""

    action: PlannedAction
    executed: bool
    succeeded: bool
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    message: str = ""


def summarise(detections: Iterable[Detection]) -> dict[Status, int]:
    counts: dict[Status, int] = {s: 0 for s in Status}
    for det in detections:
        counts[det.status] += 1
    return counts
