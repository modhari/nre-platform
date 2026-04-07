from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


STRONG_ANCHORS = (
    "evpn",
    "ethernet-vpn",
    "l2vpn-evpn",
    "vxlan",
    "vni",
    "nve",
    "vtep",
    "remote-vtep",
    "source-vtep",
    "mac-vrf",
    "ethernet-segment",
    "esi",
    "bridge-domain",
)

WEAK_ANCHORS = (
    "route-target",
    "route-distinguisher",
    "mac-ip",
    "ingress-replication",
    "flood",
    "anycast-gateway",
    "irb",
    "network-instance",
)

GENERIC_ONLY_TERMS = (
    "state",
    "statistics",
    "counters",
    "peer",
    "neighbor",
    "afi-safi",
    "bgp",
    "telemetry",
    "oper",
    "operational",
)


@dataclass(frozen=True)
class RefinedPathCandidate:
    path: str
    source_module: str | None
    vendor: str | None
    source_name: str | None
    classification: str
    confidence: str
    semantic_groups: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RefinedModuleCandidate:
    module_name: str
    vendor: str
    source_name: str
    file_path: str
    classification: str
    confidence: str
    semantic_groups: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RefinementSummary:
    input_path_candidates: int
    input_module_candidates: int
    strong_path_candidates: int
    weak_path_candidates: int
    discarded_path_candidates: int
    strong_module_candidates: int
    weak_module_candidates: int
    discarded_module_candidates: int
    semantic_group_counts: dict[str, int] = field(default_factory=dict)
    vendor_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvpnVxlanRefinedArtifact:
    generated_from: str
    summary: RefinementSummary
    strong_path_candidates: list[RefinedPathCandidate]
    weak_path_candidates: list[RefinedPathCandidate]
    strong_module_candidates: list[RefinedModuleCandidate]
    weak_module_candidates: list[RefinedModuleCandidate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_from": self.generated_from,
            "summary": self.summary.to_dict(),
            "strong_path_candidates": [
                item.to_dict() for item in self.strong_path_candidates
            ],
            "weak_path_candidates": [
                item.to_dict() for item in self.weak_path_candidates
            ],
            "strong_module_candidates": [
                item.to_dict() for item in self.strong_module_candidates
            ],
            "weak_module_candidates": [
                item.to_dict() for item in self.weak_module_candidates
            ],
        }


class EvpnVxlanPathRefiner:
    def __init__(self, *, extraction_artifact_path: Path) -> None:
        self.extraction_artifact_path = extraction_artifact_path

    def refine(self) -> EvpnVxlanRefinedArtifact:
        payload = json.loads(
            self.extraction_artifact_path.read_text(encoding="utf_8")
        )

        input_path_candidates = payload.get("path_candidates", [])
        input_module_candidates = payload.get("module_candidates", [])

        strong_path_candidates: list[RefinedPathCandidate] = []
        weak_path_candidates: list[RefinedPathCandidate] = []
        strong_module_candidates: list[RefinedModuleCandidate] = []
        weak_module_candidates: list[RefinedModuleCandidate] = []

        discarded_path_candidates = 0
        discarded_module_candidates = 0

        semantic_group_counts: dict[str, int] = {}
        vendor_counts: dict[str, int] = {}

        for item in input_path_candidates:
            classification = self._classify_candidate(
                searchable_text=self._path_search_text(item),
                matched_keywords=item.get("matched_keywords", []),
            )
            if classification is None:
                discarded_path_candidates += 1
                continue

            candidate = RefinedPathCandidate(
                path=item.get("path", "<unknown-path>"),
                source_module=item.get("source_module"),
                vendor=item.get("vendor"),
                source_name=item.get("source_name"),
                classification=item.get("classification", "unknown"),
                confidence=classification,
                semantic_groups=item.get("semantic_groups", []),
                matched_keywords=item.get("matched_keywords", []),
            )

            if classification == "strong":
                strong_path_candidates.append(candidate)
            else:
                weak_path_candidates.append(candidate)

            self._accumulate_counts(
                semantic_group_counts=semantic_group_counts,
                vendor_counts=vendor_counts,
                semantic_groups=candidate.semantic_groups,
                vendor=candidate.vendor,
            )

        for item in input_module_candidates:
            classification = self._classify_candidate(
                searchable_text=self._module_search_text(item),
                matched_keywords=item.get("matched_keywords", []),
            )
            if classification is None:
                discarded_module_candidates += 1
                continue

            candidate = RefinedModuleCandidate(
                module_name=item["module_name"],
                vendor=item["vendor"],
                source_name=item["source_name"],
                file_path=item["file_path"],
                classification=item.get("classification", "unknown"),
                confidence=classification,
                semantic_groups=item.get("semantic_groups", []),
                matched_keywords=item.get("matched_keywords", []),
            )

            if classification == "strong":
                strong_module_candidates.append(candidate)
            else:
                weak_module_candidates.append(candidate)

        strong_path_candidates.sort(
            key=lambda item: (
                item.vendor or "",
                item.source_module or "",
                item.path,
            )
        )
        weak_path_candidates.sort(
            key=lambda item: (
                item.vendor or "",
                item.source_module or "",
                item.path,
            )
        )
        strong_module_candidates.sort(
            key=lambda item: (
                item.vendor,
                item.module_name,
                item.file_path,
            )
        )
        weak_module_candidates.sort(
            key=lambda item: (
                item.vendor,
                item.module_name,
                item.file_path,
            )
        )

        summary = RefinementSummary(
            input_path_candidates=len(input_path_candidates),
            input_module_candidates=len(input_module_candidates),
            strong_path_candidates=len(strong_path_candidates),
            weak_path_candidates=len(weak_path_candidates),
            discarded_path_candidates=discarded_path_candidates,
            strong_module_candidates=len(strong_module_candidates),
            weak_module_candidates=len(weak_module_candidates),
            discarded_module_candidates=discarded_module_candidates,
            semantic_group_counts=dict(sorted(semantic_group_counts.items())),
            vendor_counts=dict(sorted(vendor_counts.items())),
        )

        return EvpnVxlanRefinedArtifact(
            generated_from=str(self.extraction_artifact_path),
            summary=summary,
            strong_path_candidates=strong_path_candidates,
            weak_path_candidates=weak_path_candidates,
            strong_module_candidates=strong_module_candidates,
            weak_module_candidates=weak_module_candidates,
        )

    def _classify_candidate(
        self,
        *,
        searchable_text: str,
        matched_keywords: list[str],
    ) -> str | None:
        text = searchable_text.lower()
        matched = {keyword.lower() for keyword in matched_keywords}

        strong_hits = {
            anchor for anchor in STRONG_ANCHORS if anchor in text or anchor in matched
        }
        weak_hits = {
            anchor for anchor in WEAK_ANCHORS if anchor in text or anchor in matched
        }
        generic_hits = {
            term for term in GENERIC_ONLY_TERMS if term in text or term in matched
        }

        if strong_hits:
            return "strong"

        if weak_hits and strong_hits:
            return "strong"

        if weak_hits:
            if generic_hits and not weak_hits:
                return None
            return "weak"

        if generic_hits:
            return None

        return None

    def _path_search_text(self, item: dict[str, Any]) -> str:
        parts = [
            str(item.get("path", "")),
            str(item.get("source_module", "")),
            str(item.get("vendor", "")),
            str(item.get("source_name", "")),
            " ".join(item.get("semantic_groups", [])),
            " ".join(item.get("matched_keywords", [])),
        ]
        return " ".join(parts).lower()

    def _module_search_text(self, item: dict[str, Any]) -> str:
        parts = [
            str(item.get("module_name", "")),
            str(item.get("file_path", "")),
            str(item.get("vendor", "")),
            str(item.get("source_name", "")),
            " ".join(item.get("semantic_groups", [])),
            " ".join(item.get("matched_keywords", [])),
        ]
        return " ".join(parts).lower()

    def _accumulate_counts(
        self,
        *,
        semantic_group_counts: dict[str, int],
        vendor_counts: dict[str, int],
        semantic_groups: list[str],
        vendor: str | None,
    ) -> None:
        for group in semantic_groups:
            semantic_group_counts[group] = semantic_group_counts.get(group, 0) + 1

        vendor_key = vendor or "unknown"
        vendor_counts[vendor_key] = vendor_counts.get(vendor_key, 0) + 1


def write_refined_artifact(
    artifact: EvpnVxlanRefinedArtifact,
    *,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact.to_dict(), indent=2),
        encoding="utf_8",
    )
    LOG.info("Wrote EVPN VXLAN refined artifact to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    repo_root = Path(__file__).resolve().parents[2]
    extraction_artifact_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "evpn_vxlan_path_candidates.json"
    )
    output_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "evpn_vxlan_path_candidates_refined.json"
    )

    refiner = EvpnVxlanPathRefiner(
        extraction_artifact_path=extraction_artifact_path
    )
    artifact = refiner.refine()
    write_refined_artifact(artifact, output_path=output_path)

    print("EVPN VXLAN REFINEMENT SUMMARY")
    print(json.dumps(artifact.summary.to_dict(), indent=2))
    print()
    print(f"WROTE: {output_path}")


if __name__ == "__main__":
    main()
