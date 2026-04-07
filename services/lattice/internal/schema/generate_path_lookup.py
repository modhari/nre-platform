from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


KEY_SEGMENT_RE = re.compile(r"\[[^\]]+\]")


def normalize_path(path: str) -> str:
    """
    Normalize keyed gNMI style paths into a canonical lookup form.

    Example:
    /interfaces/interface[name=Ethernet3]/state/counters/in-octets
    becomes
    /interfaces/interface/state/counters/in-octets
    """
    return KEY_SEGMENT_RE.sub("", path)


class PathFamilyLookupGenerator:
    def __init__(self, path_semantics_path: Path) -> None:
        self.path_semantics_path = path_semantics_path

    def build(self) -> dict[str, Any]:
        LOG.info("Loading path semantics from %s", self.path_semantics_path)
        payload = json.loads(self.path_semantics_path.read_text(encoding="utf_8"))

        semantic_families = payload["semantic_families"]
        lookup: dict[str, str] = {}
        family_counts: dict[str, int] = {}

        for family, records in semantic_families.items():
            family_counts[family] = 0

            for record in records:
                raw_path = record["path"]
                normalized = normalize_path(raw_path)

                if normalized not in lookup:
                    lookup[normalized] = family
                    family_counts[family] += 1

        output = {
            "generated_from": str(self.path_semantics_path),
            "total_lookup_paths": len(lookup),
            "path_to_family": dict(sorted(lookup.items())),
            "family_counts": dict(sorted(family_counts.items())),
        }
        return output


def write_output(output: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf_8")
    LOG.info("Wrote path family lookup to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    repo_root = Path(__file__).resolve().parents[2]
    path_semantics_path = repo_root / "data" / "generated" / "schema" / "path_semantics.json"
    output_path = repo_root / "data" / "generated" / "schema" / "path_family_lookup.json"

    LOG.info("Starting path family lookup generation")
    generator = PathFamilyLookupGenerator(path_semantics_path=path_semantics_path)
    output = generator.build()
    write_output(output, output_path)


if __name__ == "__main__":
    main()
