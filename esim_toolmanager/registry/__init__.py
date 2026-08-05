from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Iterable, Optional

from ..models import Criticality, ToolSpec

DEFAULT_REGISTRY = "tools.json"


class RegistryError(RuntimeError):
    ...


class Registry:
    """The parsed tool list. Validates hard, because a typo in the JSON would
    otherwise only surface as a confusing runtime failure much later."""

    def __init__(self, tools: dict[str, ToolSpec], meta: dict) -> None:
        self._tools = tools
        self.meta = meta

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Registry":
        if path is None:
            text = resources.files(__package__).joinpath(DEFAULT_REGISTRY).read_text("utf-8")
            origin = f"<bundled {DEFAULT_REGISTRY}>"
        else:
            if not path.is_file():
                raise RegistryError(f"registry file not found: {path}")
            text = path.read_text("utf-8")
            origin = str(path)

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RegistryError(f"{origin} is not valid JSON: {exc}") from exc

        raw_tools = payload.get("tools")
        if not isinstance(raw_tools, dict) or not raw_tools:
            raise RegistryError(f"{origin} contains no 'tools' section")

        tools: dict[str, ToolSpec] = {}
        for name, data in raw_tools.items():
            try:
                tools[name] = ToolSpec.from_dict(name, data)
            except (KeyError, ValueError) as exc:
                raise RegistryError(f"{origin}: tool '{name}' is malformed: {exc}") from exc

        return cls(tools, payload.get("_meta", {}))

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self):
        return iter(self._tools.values())

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            raise RegistryError(
                f"unknown tool '{name}'. Known tools: {', '.join(self.names)}"
            ) from None

    def select(self, names: Optional[Iterable[str]] = None) -> tuple[ToolSpec, ...]:
        if not names:
            return tuple(self._tools.values())
        return tuple(self.get(n) for n in names)

    def by_criticality(self, level: Criticality) -> tuple[ToolSpec, ...]:
        return tuple(t for t in self._tools.values() if t.criticality is level)
