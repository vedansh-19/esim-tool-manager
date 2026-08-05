from __future__ import annotations

import sys
from typing import Optional

from ..shell import Runner
from .apt import AptBackend
from .base import Backend
from .brew import BrewBackend
from .choco import ChocoBackend

ALL_BACKENDS: tuple[Backend, ...] = (AptBackend(), BrewBackend(), ChocoBackend())

__all__ = ["Backend", "AptBackend", "BrewBackend", "ChocoBackend",
           "ALL_BACKENDS", "backends_for_platform", "select_backend", "get_backend"]


def get_backend(name: str) -> Optional[Backend]:
    for backend in ALL_BACKENDS:
        if backend.name == name:
            return backend
    return None


def backends_for_platform(platform: Optional[str] = None) -> tuple[Backend, ...]:
    plat = platform or sys.platform
    return tuple(b for b in ALL_BACKENDS if any(plat.startswith(p) for p in b.platforms))


def select_backend(
    runner: Runner,
    *,
    platform: Optional[str] = None,
    override: Optional[str] = None,
) -> tuple[Optional[Backend], str]:
    if override:
        backend = get_backend(override)
        if backend is None:
            known = ", ".join(b.name for b in ALL_BACKENDS)
            return None, f"unknown backend '{override}' (known: {known})"
        if not backend.is_available(runner):
            return backend, f"{backend.label} forced, but it is not installed here"
        return backend, f"{backend.label} (forced)"

    candidates = backends_for_platform(platform)
    if not candidates:
        return None, f"no packaging backend is known for platform '{platform or sys.platform}'"

    for backend in candidates:
        if backend.is_available(runner):
            return backend, f"{backend.label} detected"

    names = ", ".join(b.label for b in candidates)
    return None, f"no usable package manager found (looked for: {names})"
