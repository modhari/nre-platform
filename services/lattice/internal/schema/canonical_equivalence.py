from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


OPENCONFIG_SOURCE_NAMES = {
    "openconfig_public",
    "juniper_openconfig",
    "nokia_openconfig",
    "arista_openconfig",
}


@dataclass(frozen=True)
class CandidatePath:
    vendor: str
    source_name: str
    module_name: str
    file_path: str
    path: str
    node_kind: str
    leaf_type: str | None
    config_class: str
    semantic_domain: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SemanticFamilyEquivalence:
    semantic_family: str
    preferred_openconfig: str | None = None
    preferred_openconfig_source: str | None = None
    preferred_openconfig_module: str | None = None
    vendor_candidates: dict[str, list[CandidatePath]] = field(
        default_factory=dict
    )
    openconfig_candidates: list[CandidatePath] = field(
        default_factory=list
    )
    fallback_order: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_family": self.semantic_family,
            "preferred_openconfig": self.preferred_openconfig,
            "preferred_openconfig_source": (
                self.preferred_openconfig_source
            ),
            "preferred_openconfig_module": (
                self.preferred_openconfig_module
            ),
            "openconfig_candidates": [
                candidate.to_dict()
                for candidate in self.openconfig_candidates
            ],
            "vendor_candidates": {
                vendor: [candidate.to_dict() for candidate in candidates]
                for vendor, candidates in self.vendor_candidates.items()
            },
            "fallback_order": self.fallback_order,
        }


class CanonicalEquivalenceBuilder:
    def __init__(self, path_semantics_path: Path) -> None:
        self.path_semantics_path = path_semantics_path

    def build(self) -> dict[str, Any]:
        LOG.info("Loading path semantics from %s", self.path_semantics_path)
        payload = json.loads(
            self.path_semantics_path.read_text(encoding="utf_8")
        )

        semantic_families = payload["semantic_families"]
        LOG.info("Loaded %s semantic families", len(semantic_families))

        equivalence_registry: dict[str, SemanticFamilyEquivalence] = {}
        summary: dict[str, Any] = {}

        for family_name, records in semantic_families.items():
            equivalence = self._build_family_equivalence(
                family_name=family_name,
                records=records,
            )
            equivalence_registry[family_name] = equivalence
            summary[family_name] = self._build_family_summary(
                equivalence
            )

        output = {
            "generated_from": str(self.path_semantics_path),
            "semantic_families": {
                family_name: equivalence.to_dict()
                for family_name, equivalence in sorted(
                    equivalence_registry.items()
                )
            },
            "summary": dict(sorted(summary.items())),
        }
        return output

    def _build_family_equivalence(
        self,
        family_name: str,
        records: list[dict[str, Any]],
    ) -> SemanticFamilyEquivalence:
        openconfig_candidates: list[CandidatePath] = []
        vendor_candidates: dict[str, list[CandidatePath]] = defaultdict(
            list
        )

        for record in records:
            candidate = CandidatePath(
                vendor=record["vendor"],
                source_name=record["source_name"],
                module_name=record["module_name"],
                file_path=record["file_path"],
                path=record["path"],
                node_kind=record["node_kind"],
                leaf_type=record.get("leaf_type"),
                config_class=record.get("config_class", "unknown"),
                semantic_domain=record.get("semantic_domain", "misc"),
            )

            vendor_candidates[candidate.vendor].append(candidate)

            if candidate.source_name in OPENCONFIG_SOURCE_NAMES:
                openconfig_candidates.append(candidate)

        openconfig_candidates = self._dedupe_and_sort_candidates(
            openconfig_candidates
        )

        deduped_vendor_candidates = {
            vendor: self._dedupe_and_sort_candidates(candidates)
            for vendor, candidates in vendor_candidates.items()
        }

        preferred_openconfig = None
        preferred_openconfig_source = None
        preferred_openconfig_module = None

        if openconfig_candidates:
            preferred = self._pick_preferred_openconfig(
                openconfig_candidates
            )
            preferred_openconfig = preferred.path
            preferred_openconfig_source = preferred.source_name
            preferred_openconfig_module = preferred.module_name

        fallback_order = self._build_fallback_order(
            preferred_openconfig=preferred_openconfig,
            vendor_candidates=deduped_vendor_candidates,
        )

        return SemanticFamilyEquivalence(
            semantic_family=family_name,
            preferred_openconfig=preferred_openconfig,
            preferred_openconfig_source=preferred_openconfig_source,
            preferred_openconfig_module=preferred_openconfig_module,
            vendor_candidates=dict(sorted(deduped_vendor_candidates.items())),
            openconfig_candidates=openconfig_candidates,
            fallback_order=fallback_order,
        )

    def _dedupe_and_sort_candidates(
        self,
        candidates: list[CandidatePath],
    ) -> list[CandidatePath]:
        seen: set[tuple[str, str, str]] = set()
        unique: list[CandidatePath] = []

        for candidate in candidates:
            key = (
                candidate.source_name,
                candidate.module_name,
                candidate.path,
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)

        return sorted(
            unique,
            key=lambda candidate: (
                self._source_priority(candidate.source_name),
                candidate.module_name,
                candidate.path,
            ),
        )

    def _pick_preferred_openconfig(
        self,
        candidates: list[CandidatePath],
    ) -> CandidatePath:
        return sorted(
            candidates,
            key=lambda candidate: (
                self._source_priority(candidate.source_name),
                self._module_priority(candidate.module_name),
                candidate.path,
            ),
        )[0]

    def _build_fallback_order(
        self,
        preferred_openconfig: str | None,
        vendor_candidates: dict[str, list[CandidatePath]],
    ) -> list[str]:
        order: list[str] = []

        if preferred_openconfig:
            order.append("openconfig")

        for vendor in sorted(vendor_candidates):
            if not vendor_candidates[vendor]:
                continue
            order.append(vendor)

        return order

    def _build_family_summary(
        self,
        equivalence: SemanticFamilyEquivalence,
    ) -> dict[str, Any]:
        vendor_counts = {
            vendor: len(candidates)
            for vendor, candidates in equivalence.vendor_candidates.items()
        }

        return {
            "preferred_openconfig": equivalence.preferred_openconfig,
            "preferred_openconfig_source": (
                equivalence.preferred_openconfig_source
            ),
            "vendors_present": sorted(
                equivalence.vendor_candidates.keys()
            ),
            "vendor_candidate_counts": dict(
                sorted(vendor_counts.items())
            ),
            "openconfig_candidate_count": len(
                equivalence.openconfig_candidates
            ),
            "fallback_order": equivalence.fallback_order,
        }

    def _source_priority(self, source_name: str) -> int:
        priorities = {
            "openconfig_public": 0,
            "juniper_openconfig": 1,
            "nokia_openconfig": 1,
            "arista_openconfig": 1,
            "juniper_native": 2,
            "arista_native": 2,
            "yangmodels_catalog": 3,
        }
        return priorities.get(source_name, 99)

    def _module_priority(self, module_name: str) -> int:
        lowered = module_name.lower()
        if lowered.startswith("openconfig-"):
            return 0
        return 1


def write_output(output: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf_8")
    LOG.info("Wrote canonical equivalence to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    repo_root = Path(__file__).resolve().parents[2]
    path_semantics_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "path_semantics.json"
    )
    output_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "canonical_equivalence.json"
    )

    LOG.info("Starting canonical equivalence build")
    builder = CanonicalEquivalenceBuilder(
        path_semantics_path=path_semantics_path
    )
    output = builder.build()
    write_output(output, output_path)


if __name__ == "__main__":
    main()
