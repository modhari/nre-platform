from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


TARGET_VENDORS = ("juniper", "arista", "nokia", "cisco", "shared", "neutral")


@dataclass(frozen=True)
class VendorCapabilityCoverage:
    vendor: str
    capability: str
    path_count: int
    module_count: int
    config_path_count: int
    state_path_count: int
    high_confidence_count: int
    medium_confidence_count: int
    low_confidence_count: int
    status: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CoverageSummaryArtifact:
    generated_from: str
    vendor_capability_coverage: list[VendorCapabilityCoverage]
    vendor_summary: dict[str, dict[str, Any]]
    capability_summary: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_from": self.generated_from,
            "vendor_capability_coverage": [
                item.to_dict() for item in self.vendor_capability_coverage
            ],
            "vendor_summary": self.vendor_summary,
            "capability_summary": self.capability_summary,
        }


class EvpnVxlanCoverageSummarizer:
    def __init__(self, *, capability_artifact_path: Path) -> None:
        self.capability_artifact_path = capability_artifact_path

    def summarize(self) -> CoverageSummaryArtifact:
        payload = json.loads(self.capability_artifact_path.read_text(encoding="utf_8"))
        path_mappings = payload.get("path_mappings", [])
        module_mappings = payload.get("module_mappings", [])

        capabilities = sorted(
            {
                item["capability"]
                for item in path_mappings
            }
            | {
                item["capability"]
                for item in module_mappings
            }
        )

        coverage_rows: list[VendorCapabilityCoverage] = []

        for vendor in TARGET_VENDORS:
            for capability in capabilities:
                vendor_paths = [
                    item
                    for item in path_mappings
                    if item.get("vendor") == vendor and item.get("capability") == capability
                ]
                vendor_modules = [
                    item
                    for item in module_mappings
                    if item.get("vendor") == vendor and item.get("capability") == capability
                ]

                path_count = len(vendor_paths)
                module_count = len(vendor_modules)
                config_path_count = sum(
                    1 for item in vendor_paths if item.get("classification") == "config"
                )
                state_path_count = sum(
                    1 for item in vendor_paths if item.get("classification") == "state"
                )
                high_confidence_count = sum(
                    1 for item in vendor_paths if item.get("confidence") == "high"
                )
                medium_confidence_count = sum(
                    1 for item in vendor_paths if item.get("confidence") == "medium"
                )
                low_confidence_count = sum(
                    1 for item in vendor_paths if item.get("confidence") == "low"
                )

                status, notes = self._classify_status(
                    path_count=path_count,
                    module_count=module_count,
                    config_path_count=config_path_count,
                    state_path_count=state_path_count,
                    high_confidence_count=high_confidence_count,
                    medium_confidence_count=medium_confidence_count,
                )

                coverage_rows.append(
                    VendorCapabilityCoverage(
                        vendor=vendor,
                        capability=capability,
                        path_count=path_count,
                        module_count=module_count,
                        config_path_count=config_path_count,
                        state_path_count=state_path_count,
                        high_confidence_count=high_confidence_count,
                        medium_confidence_count=medium_confidence_count,
                        low_confidence_count=low_confidence_count,
                        status=status,
                        notes=notes,
                    )
                )

        coverage_rows.sort(key=lambda item: (item.vendor, item.capability))

        vendor_summary = self._build_vendor_summary(coverage_rows)
        capability_summary = self._build_capability_summary(coverage_rows)

        return CoverageSummaryArtifact(
            generated_from=str(self.capability_artifact_path),
            vendor_capability_coverage=coverage_rows,
            vendor_summary=vendor_summary,
            capability_summary=capability_summary,
        )

    def _classify_status(
        self,
        *,
        path_count: int,
        module_count: int,
        config_path_count: int,
        state_path_count: int,
        high_confidence_count: int,
        medium_confidence_count: int,
    ) -> tuple[str, list[str]]:
        notes: list[str] = []

        if path_count == 0 and module_count == 0:
            return "absent", ["No mapped paths or modules found"]

        if state_path_count > 0:
            notes.append("Operational state candidates exist")
        if config_path_count > 0:
            notes.append("Configuration candidates exist")
        if high_confidence_count > 0:
            notes.append("High confidence candidates exist")
        if medium_confidence_count > 0:
            notes.append("Medium confidence candidates exist")

        if state_path_count > 0 and config_path_count > 0 and high_confidence_count > 0:
            return "claimable", notes

        if (state_path_count > 0 or config_path_count > 0) and (
            high_confidence_count > 0 or medium_confidence_count > 0
        ):
            return "partial", notes

        return "weak", notes

    def _build_vendor_summary(
        self,
        coverage_rows: list[VendorCapabilityCoverage],
    ) -> dict[str, dict[str, Any]]:
        summary: dict[str, dict[str, Any]] = {}

        for vendor in TARGET_VENDORS:
            rows = [row for row in coverage_rows if row.vendor == vendor]
            summary[vendor] = {
                "claimable_capabilities": sorted(
                    [row.capability for row in rows if row.status == "claimable"]
                ),
                "partial_capabilities": sorted(
                    [row.capability for row in rows if row.status == "partial"]
                ),
                "weak_capabilities": sorted(
                    [row.capability for row in rows if row.status == "weak"]
                ),
                "absent_capabilities": sorted(
                    [row.capability for row in rows if row.status == "absent"]
                ),
            }

        return summary

    def _build_capability_summary(
        self,
        coverage_rows: list[VendorCapabilityCoverage],
    ) -> dict[str, dict[str, Any]]:
        capabilities = sorted({row.capability for row in coverage_rows})
        summary: dict[str, dict[str, Any]] = {}

        for capability in capabilities:
            rows = [row for row in coverage_rows if row.capability == capability]
            summary[capability] = {
                "claimable_vendors": sorted(
                    [row.vendor for row in rows if row.status == "claimable"]
                ),
                "partial_vendors": sorted(
                    [row.vendor for row in rows if row.status == "partial"]
                ),
                "weak_vendors": sorted(
                    [row.vendor for row in rows if row.status == "weak"]
                ),
                "absent_vendors": sorted(
                    [row.vendor for row in rows if row.status == "absent"]
                ),
            }

        return summary


def write_coverage_summary(
    artifact: CoverageSummaryArtifact,
    *,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact.to_dict(), indent=2),
        encoding="utf_8",
    )
    LOG.info("Wrote EVPN VXLAN coverage summary to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    repo_root = Path(__file__).resolve().parents[2]
    capability_artifact_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "evpn_vxlan_capability_map.json"
    )
    output_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "evpn_vxlan_coverage_summary.json"
    )

    summarizer = EvpnVxlanCoverageSummarizer(
        capability_artifact_path=capability_artifact_path
    )
    artifact = summarizer.summarize()
    write_coverage_summary(artifact, output_path=output_path)

    print("EVPN VXLAN COVERAGE SUMMARY")
    print(json.dumps(artifact.vendor_summary, indent=2))
    print()
    print("CAPABILITY VIEW")
    print(json.dumps(artifact.capability_summary, indent=2))
    print()
    print(f"WROTE: {output_path}")


if __name__ == "__main__":
    main()
