from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Protocol, Tuple


@dataclass(frozen=True)
class GnmiPath:
    origin: str
    path: str


@dataclass(frozen=True)
class GnmiUpdate:
    path: GnmiPath
    ts_unix_s: float
    value: float
    labels: Dict[str, str]


class GnmiClient(Protocol):
    def capabilities(self) -> Dict[str, str]:
        raise NotImplementedError

    def get(self, paths: List[GnmiPath]) -> List[GnmiUpdate]:
        raise NotImplementedError


class FakeGnmiClient:
    def __init__(self, models: Dict[str, str], updates: List[GnmiUpdate]) -> None:
        self._models = dict(models)
        self._updates = list(updates)
        self._get_calls: List[Tuple[str, str]] = []

    def capabilities(self) -> Dict[str, str]:
        return dict(self._models)

    def get(self, paths: List[GnmiPath]) -> List[GnmiUpdate]:
        want = {(p.origin, p.path) for p in paths}
        for p in paths:
            self._get_calls.append((p.origin, p.path))
        return [u for u in self._updates if (u.path.origin, u.path.path) in want]

    @property
    def get_calls(self) -> List[Tuple[str, str]]:
        return list(self._get_calls)
