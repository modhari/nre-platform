from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


CAPABILITY_RULES: dict[str, dict[str, Any]] = {
    "bgp_evpn_peer_state": {
        "required_any": (
            ("evpn", "l2vpn-evpn", "ethernet-vpn"),
            ("peer", "neighbor", "afi-safi"),
        ),
        "preferred": ("bgp", "state", "session-state", "peer-state"),
        "allowed_classifications": {"state"},
    },
    "bgp_evpn_peer_config": {
        "required_any": (
            ("evpn", "l2vpn-evpn", "ethernet-vpn"),
            ("peer", "neighbor", "afi-safi"),
        ),
        "preferred": ("bgp", "config"),
        "allowed_classifications": {"config", "unknown"},
    },
    "vxlan_vni_oper_state": {
        "required_any": (
            ("vxlan", "vni", "nve", "vtep"),
            ("state", "statistics", "oper", "operational"),
        ),
        "preferred": ("bridge-domain", "network-instance", "remote-vtep"),
        "allowed_classifications": {"state"},
    },
    "vxlan_vni_config": {
        "required_any": (
            ("vxlan", "vni", "nve", "vtep"),
            ("config", "bridge-domain", "network-instance"),
        ),
        "preferred": ("source-vtep", "remote-vtep", "ingress-replication"),
        "allowed_classifications": {"config", "unknown"},
    },
    "evpn_mac_vrf_state": {
        "required_any": (
            ("evpn", "ethernet-vpn", "mac-vrf"),
            ("state", "statistics", "oper", "operational"),
        ),
        "preferred": ("bridge-domain", "network-instance", "mac-ip"),
        "allowed_classifications": {"state"},
    },
    "evpn_mac_vrf_config": {
        "required_any": (
            ("evpn", "ethernet-vpn", "mac-vrf"),
            ("config", "bridge-domain", "network-instance"),
        ),
        "preferred": ("route-target", "route-distinguisher", "vni"),
        "allowed_classifications": {"config", "unknown"},
    },
    "evpn_vtep_state": {
        "required_any": (
            ("vtep", "remote-vtep", "source-vtep", "nve"),
            ("state", "statistics", "oper", "operational"),
        ),
        "preferred": ("vxlan", "evpn"),
        "allowed_classifications": {"state"},
    },
    "evpn_vtep_config": {
        "required_any": (
            ("vtep", "remote-vtep", "source-vtep", "nve"),
            ("config", "vxlan"),
        ),
        "preferred": ("evpn", "ingress-replication"),
        "allowed_classifications": {"config", "unknown"},
    },
}


@dataclass(frozen=True)
class CapabilityPathMapping:
    capability: str
    path: str
    source_module: str | None
    vendor: str | None
    source_name: str | None
    classification: str
    confidence: str
    score: int
    semantic_groups: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityModuleMapping:
    capability: str
    module_name: str
    vendor: str
    source_name: str
    file_path: str
    classification: str
    confidence: str
    score: int
    semantic_groups: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilitySummary:
    capability_counts: dict[str, int] = field(default_factory=dict)
    vendor_counts: dict[str, int] = field(default_factory=dict)
    total_path_mappings: int = 0
    total_module_mappings: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvpnVxlanCapabilityArtifact:
    generated_from: str
    summary: CapabilitySummary
    path_mappings: list[CapabilityPathMapping]
    module_mappings: list[CapabilityModuleMapping]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_from": self.generated_from,
            "summary": self.summary.to_dict(),
            "path_mappings": [item.to_dict() for item in self.path_mappings],
            "module_mappings": [item.to_dict() for item in self.module_mappings],
        }


class EvpnVxlanCapabilityMapper:
    def __init__(self, *, refined_artifact_path: Path) -> None:
        self.refined_artifact_path = refined_artifact_path

    def map_capabilities(self) -> EvpnVxlanCapabilityArtifact:
        payload = json.loads(self.refined_artifact_path.read_text(encoding="utf_8"))

        strong_paths = payload.get("strong_path_candidates", [])
        weak_paths = payload.get("weak_path_candidates", [])
        strong_modules = payload.get("strong_module_candidates", [])
        weak_modules = payload.get("weak_module_candidates", [])

        path_mappings: list[CapabilityPathMapping] = []
        module_mappings: list[CapabilityModuleMapping] = []

        capability_counts: dict[str, int] = {}
        vendor_counts: dict[str, int] = {}

        for item in strong_paths + weak_paths:
            mapping = self._map_path_candidate(item)
            if mapping is None:
                continue
            path_mappings.append(mapping)
            capability_counts[mapping.capability] = (
                capability_counts.get(mapping.capability, 0) + 1
            )
            vendor_key = mapping.vendor or "unknown"
            vendor_counts[vendor_key] = vendor_counts.get(vendor_key, 0) + 1

        for item in strong_modules + weak_modules:
            mapping = self._map_module_candidate(item)
            if mapping is None:
                continue
            module_mappings.append(mapping)

        path_mappings.sort(
            key=lambda item: (
                item.capability,
                item.vendor or "",
                item.source_module or "",
                item.path,
            )
        )
        module_mappings.sort(
            key=lambda item: (
                item.capability,
                item.vendor,
                item.module_name,
                item.file_path,
            )
        )

        summary = CapabilitySummary(
            capability_counts=dict(sorted(capability_counts.items())),
            vendor_counts=dict(sorted(vendor_counts.items())),
            total_path_mappings=len(path_mappings),
            total_module_mappings=len(module_mappings),
        )

        return EvpnVxlanCapabilityArtifact(
            generated_from=str(self.refined_artifact_path),
            summary=summary,
            path_mappings=path_mappings,
            module_mappings=module_mappings,
        )

    def _map_path_candidate(
        self,
        item: dict[str, Any],
    ) -> CapabilityPathMapping | None:
        searchable_text = self._candidate_search_text(item)
        classification = item.get("classification", "unknown")
        best = self._best_capability_match(
            searchable_text=searchable_text,
            classification=classification,
        )
        if best is None:
            return None

        capability, score = best
        confidence = self._confidence_from_score(score)

        return CapabilityPathMapping(
            capability=capability,
            path=item.get("path", "<unknown-path>"),
            source_module=item.get("source_module"),
            vendor=item.get("vendor"),
            source_name=item.get("source_name"),
            classification=classification,
            confidence=confidence,
            score=score,
            semantic_groups=item.get("semantic_groups", []),
            matched_keywords=item.get("matched_keywords", []),
        )

    def _map_module_candidate(
        self,
        item: dict[str, Any],
    ) -> CapabilityModuleMapping | None:
        searchable_text = self._candidate_search_text(item)
        classification = item.get("classification", "unknown")
        best = self._best_capability_match(
            searchable_text=searchable_text,
            classification=classification,
        )
        if best is None:
            return None

        capability, score = best
        confidence = self._confidence_from_score(score)

        return CapabilityModuleMapping(
            capability=capability,
            module_name=item["module_name"],
            vendor=item["vendor"],
            source_name=item["source_name"],
            file_path=item["file_path"],
            classification=classification,
            confidence=confidence,
            score=score,
            semantic_groups=item.get("semantic_groups", []),
            matched_keywords=item.get("matched_keywords", []),
        )

    def _best_capability_match(
        self,
        *,
        searchable_text: str,
        classification: str,
    ) -> tuple[str, int] | None:
        text = searchable_text.lower()
        best_capability: str | None = None
        best_score = -1

        for capability, rule in CAPABILITY_RULES.items():
            allowed_classifications = rule["allowed_classifications"]
            if classification not in allowed_classifications:
                continue

            required_groups = rule["required_any"]
            if not all(any(token in text for token in group) for group in required_groups):
                continue

            preferred = rule["preferred"]
            preferred_hits = sum(1 for token in preferred if token in text)
            required_hits = sum(
                1
                for group in required_groups
                for token in group
                if token in text
            )
            score = (required_hits * 10) + preferred_hits

            if score > best_score:
                best_capability = capability
                best_score = score

        if best_capability is None:
            return None

        return best_capability, best_score

    def _candidate_search_text(self, item: dict[str, Any]) -> str:
        parts = [
            str(item.get("path", "")),
            str(item.get("source_module", "")),
            str(item.get("module_name", "")),
            str(item.get("vendor", "")),
            str(item.get("source_name", "")),
            str(item.get("file_path", "")),
            " ".join(item.get("semantic_groups", [])),
            " ".join(item.get("matched_keywords", [])),
        ]
        return " ".join(parts).lower()

    def _confidence_from_score(self, score: int) -> str:
        if score >= 25:
            return "high"
        if score >= 15:
            return "medium"
        return "low"


def write_capability_artifact(
    artifact: EvpnVxlanCapabilityArtifact,
    *,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact.to_dict(), indent=2),
        encoding="utf_8",
    )
    LOG.info("Wrote EVPN VXLAN capability artifact to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    repo_root = Path(__file__).resolve().parents[2]
    refined_artifact_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "evpn_vxlan_path_candidates_refined.json"
    )
    output_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "evpn_vxlan_capability_map.json"
    )

    mapper = EvpnVxlanCapabilityMapper(
        refined_artifact_path=refined_artifact_path
    )
    artifact = mapper.map_capabilities()
    write_capability_artifact(artifact, output_path=output_path)

    print("EVPN VXLAN CAPABILITY MAPPING SUMMARY")
    print(json.dumps(artifact.summary.to_dict(), indent=2))
    print()
    print(f"WROTE: {output_path}")


if __name__ == "__main__":
    main()
