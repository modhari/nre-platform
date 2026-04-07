from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


EVPN_VXLAN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "evpn": (
        "evpn",
        "ethernet-vpn",
        "mac-vrf",
        "ethernet-segment",
        "esi",
        "route-target",
        "route-distinguisher",
        "type-2",
        "type-3",
        "type-5",
        "mac-ip",
    ),
    "vxlan": (
        "vxlan",
        "vni",
        "nve",
        "vtep",
        "remote-vtep",
        "source-vtep",
        "ingress-replication",
        "flood",
        "bridge-domain",
        "tunnel",
    ),
    "bgp_evpn": (
        "bgp",
        "evpn",
        "afi-safi",
        "l2vpn-evpn",
        "neighbor",
        "peer",
    ),
    "l2_l3_services": (
        "bridge-domain",
        "network-instance",
        "mac-vrf",
        "l2vpn",
        "l3vpn",
        "vlan",
        "irb",
        "integrated-routing-and-bridging",
        "anycast-gateway",
    ),
    "telemetry": (
        "state",
        "counters",
        "statistics",
        "oper",
        "operational",
        "peer-state",
        "session-state",
    ),
}


@dataclass(frozen=True)
class ExtractedPathCandidate:
    path: str
    source_module: str | None
    vendor: str | None
    source_name: str | None
    classification: str
    semantic_groups: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    raw_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExtractedModuleCandidate:
    module_name: str
    vendor: str
    source_name: str
    file_path: str
    classification: str
    semantic_groups: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExtractionSummary:
    total_path_candidates: int
    total_module_candidates: int
    config_paths: int
    state_paths: int
    unknown_paths: int
    semantic_group_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvpnVxlanExtractionArtifact:
    generated_from_path_index: str
    generated_from_schema_catalog: str
    summary: ExtractionSummary
    path_candidates: list[ExtractedPathCandidate]
    module_candidates: list[ExtractedModuleCandidate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_from_path_index": self.generated_from_path_index,
            "generated_from_schema_catalog": self.generated_from_schema_catalog,
            "summary": self.summary.to_dict(),
            "path_candidates": [item.to_dict() for item in self.path_candidates],
            "module_candidates": [item.to_dict() for item in self.module_candidates],
        }


class EvpnVxlanPathExtractor:
    def __init__(
        self,
        *,
        path_index_path: Path,
        schema_catalog_path: Path,
    ) -> None:
        self.path_index_path = path_index_path
        self.schema_catalog_path = schema_catalog_path

    def extract(self) -> EvpnVxlanExtractionArtifact:
        path_candidates = self._extract_path_candidates()
        module_candidates = self._extract_module_candidates()

        semantic_group_counts: dict[str, int] = {}
        for item in path_candidates:
            for group in item.semantic_groups:
                semantic_group_counts[group] = semantic_group_counts.get(group, 0) + 1

        config_paths = sum(1 for item in path_candidates if item.classification == "config")
        state_paths = sum(1 for item in path_candidates if item.classification == "state")
        unknown_paths = sum(1 for item in path_candidates if item.classification == "unknown")

        summary = ExtractionSummary(
            total_path_candidates=len(path_candidates),
            total_module_candidates=len(module_candidates),
            config_paths=config_paths,
            state_paths=state_paths,
            unknown_paths=unknown_paths,
            semantic_group_counts=dict(sorted(semantic_group_counts.items())),
        )

        return EvpnVxlanExtractionArtifact(
            generated_from_path_index=str(self.path_index_path),
            generated_from_schema_catalog=str(self.schema_catalog_path),
            summary=summary,
            path_candidates=path_candidates,
            module_candidates=module_candidates,
        )

    def _extract_path_candidates(self) -> list[ExtractedPathCandidate]:
        candidates: list[ExtractedPathCandidate] = []

        with self.path_index_path.open("r", encoding="utf_8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue

                record = json.loads(line)
                searchable_text = self._build_searchable_text(record)
                semantic_groups, matched_keywords = self._match_keywords(searchable_text)

                if not semantic_groups:
                    continue

                path = self._extract_path_string(record)
                classification = self._classify_path(path=path, record=record)

                candidates.append(
                    ExtractedPathCandidate(
                        path=path,
                        source_module=record.get("module_name"),
                        vendor=record.get("vendor"),
                        source_name=record.get("source_name"),
                        classification=classification,
                        semantic_groups=semantic_groups,
                        matched_keywords=matched_keywords,
                        raw_record=record,
                    )
                )

        candidates.sort(
            key=lambda item: (
                item.vendor or "",
                item.source_module or "",
                item.path,
            )
        )
        return candidates

    def _extract_module_candidates(self) -> list[ExtractedModuleCandidate]:
        payload = json.loads(self.schema_catalog_path.read_text(encoding="utf_8"))
        modules = payload.get("modules", [])

        candidates: list[ExtractedModuleCandidate] = []

        for module in modules:
            searchable_text = " ".join(
                [
                    str(module.get("module_name", "")),
                    str(module.get("file_path", "")),
                    " ".join(module.get("semantic_domains", [])),
                    " ".join(module.get("augments", [])),
                    " ".join(module.get("deviations", [])),
                    " ".join(module.get("imports", [])),
                    " ".join(module.get("includes", [])),
                ]
            ).lower()

            semantic_groups, matched_keywords = self._match_keywords(searchable_text)
            if not semantic_groups:
                continue

            classification = self._classify_module(module)

            candidates.append(
                ExtractedModuleCandidate(
                    module_name=module["module_name"],
                    vendor=module["vendor"],
                    source_name=module["source_name"],
                    file_path=module["file_path"],
                    classification=classification,
                    semantic_groups=semantic_groups,
                    matched_keywords=matched_keywords,
                )
            )

        candidates.sort(
            key=lambda item: (
                item.vendor,
                item.module_name,
                item.file_path,
            )
        )
        return candidates

    def _build_searchable_text(self, record: dict[str, Any]) -> str:
        parts = [
            str(record.get("path", "")),
            str(record.get("xpath", "")),
            str(record.get("module_name", "")),
            str(record.get("vendor", "")),
            str(record.get("source_name", "")),
            str(record.get("description", "")),
            str(record.get("container", "")),
            str(record.get("leaf", "")),
            str(record.get("leaf_type", "")),
            str(record.get("node_type", "")),
        ]
        return " ".join(parts).lower()

    def _match_keywords(self, searchable_text: str) -> tuple[list[str], list[str]]:
        semantic_groups: list[str] = []
        matched_keywords: list[str] = []

        for group, keywords in EVPN_VXLAN_KEYWORDS.items():
            group_matches = [keyword for keyword in keywords if keyword in searchable_text]
            if group_matches:
                semantic_groups.append(group)
                matched_keywords.extend(group_matches)

        return sorted(set(semantic_groups)), sorted(set(matched_keywords))

    def _extract_path_string(self, record: dict[str, Any]) -> str:
        for key in ("path", "xpath", "gnmi_path", "openconfig_path"):
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return "<unknown-path>"

    def _classify_path(self, *, path: str, record: dict[str, Any]) -> str:
        lowered_path = path.lower()

        if "/state/" in lowered_path or lowered_path.endswith("/state"):
            return "state"
        if "/config/" in lowered_path or lowered_path.endswith("/config"):
            return "config"

        node_type = str(record.get("node_type", "")).lower()
        description = str(record.get("description", "")).lower()

        if "counter" in node_type or "stat" in node_type:
            return "state"
        if "oper" in description or "state" in description:
            return "state"

        return "unknown"

    def _classify_module(self, module: dict[str, Any]) -> str:
        text = " ".join(
            [
                str(module.get("module_name", "")),
                str(module.get("file_path", "")),
                " ".join(module.get("semantic_domains", [])),
            ]
        ).lower()

        if "state" in text or "oper" in text or "telemetry" in text:
            return "state"
        if "config" in text:
            return "config"
        return "unknown"


def write_extraction_artifact(
    artifact: EvpnVxlanExtractionArtifact,
    *,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact.to_dict(), indent=2),
        encoding="utf_8",
    )
    LOG.info("Wrote EVPN VXLAN extraction artifact to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    repo_root = Path(__file__).resolve().parents[2]
    
    def find_file(repo_root: Path, filename: str) -> Path:
        matches = list(repo_root.rglob(filename))
        if not matches:
            raise FileNotFoundError(f"Could not find {filename} under {repo_root}")
        if len(matches) > 1:
            LOG.warning("Multiple matches for %s, using %s", filename, matches[0])
        return matches[0]
    
    path_index_path = find_file(repo_root, "path_index.jsonl")
    schema_catalog_path = find_file(repo_root, "schema_catalog.json")

    output_path = (
        repo_root / "data" / "generated" / "schema" / "evpn_vxlan_path_candidates.json"
    )

    extractor = EvpnVxlanPathExtractor(
        path_index_path=path_index_path,
        schema_catalog_path=schema_catalog_path,
    )
    artifact = extractor.extract()
    write_extraction_artifact(artifact, output_path=output_path)

    print("EVPN VXLAN EXTRACTION SUMMARY")
    print(json.dumps(artifact.summary.to_dict(), indent=2))
    print()
    print(f"WROTE: {output_path}")


if __name__ == "__main__":
    main()
