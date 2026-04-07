from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

KEY_SEGMENT_RE = re.compile(r"\[[^\]]+\]")


def normalize_lookup_path(path: str | None) -> str | None:
    if not path:
        return None
    return KEY_SEGMENT_RE.sub("", path)


@dataclass(frozen=True)
class PathFamilyLookup:
    generated_from: str
    total_lookup_paths: int
    path_to_family: dict[str, str]
    family_counts: dict[str, int]


class PathFamilyLookupLoader:
    def __init__(self, lookup_path: Path) -> None:
        self.lookup_path = lookup_path
        self._lookup: PathFamilyLookup | None = None

    def load(self) -> None:
        payload = json.loads(self.lookup_path.read_text(encoding="utf_8"))
        self._lookup = PathFamilyLookup(
            generated_from=payload["generated_from"],
            total_lookup_paths=payload["total_lookup_paths"],
            path_to_family=payload["path_to_family"],
            family_counts=payload["family_counts"],
        )

    def lookup_family(self, raw_path: str | None) -> str | None:
        if not raw_path:
            return None

        if self._lookup is None:
            self.load()

        assert self._lookup is not None
        normalized = normalize_lookup_path(raw_path)
        if not normalized:
            return None

        return self._lookup.path_to_family.get(normalized)
