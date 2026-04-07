from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


SEMANTIC_TO_CANONICAL_METRIC: dict[str, str] = {
    "interface_in_octets": "lattice_interface_in_octets_total",
    "interface_out_octets": "lattice_interface_out_octets_total",
    "interface_oper_status": "lattice_interface_oper_up",
    "interface_admin_status": "lattice_interface_admin_up",
    "bgp_session_state": "lattice_bgp_session_up",
    "bgp_prefixes_received": "lattice_bgp_prefixes_received",
    "bgp_prefixes_sent": "lattice_bgp_prefixes_sent",
    "optics_rx_power": "lattice_optics_rx_power_dbm",
    "optics_tx_power": "lattice_optics_tx_power_dbm",
    "system_cpu_utilization": "lattice_system_cpu_utilization_ratio",
    "system_memory_utilization": "lattice_system_memory_utilization_ratio",
}


SEMANTIC_TO_VALUE_TRANSFORM: dict[str, str] = {
    "interface_in_octets": "identity_transform",
    "interface_out_octets": "identity_transform",
    "interface_oper_status": "bool_up_down_transform",
    "interface_admin_status": "bool_up_down_transform",
    "bgp_session_state": "bool_up_down_transform",
    "bgp_prefixes_received": "identity_transform",
    "bgp_prefixes_sent": "identity_transform",
    "optics_rx_power": "identity_transform",
    "optics_tx_power": "identity_transform",
    "system_cpu_utilization": "identity_transform",
    "system_memory_utilization": "identity_transform",
}


SEMANTIC_TO_LABEL_EXTRACTOR: dict[str, str] = {
    "interface_in_octets": "interface_from_payload_or_path",
    "interface_out_octets": "interface_from_payload_or_path",
    "interface_oper_status": "interface_from_payload_or_path",
    "interface_admin_status": "interface_from_payload_or_path",
    "bgp_session_state": "bgp_session_labels_from_payload_or_path",
    "bgp_prefixes_received": "bgp_session_labels_from_payload_or_path",
    "bgp_prefixes_sent": "bgp_session_labels_from_payload_or_path",
    "optics_rx_power": "interface_from_payload_or_path",
    "optics_tx_power": "interface_from_payload_or_path",
    "system_cpu_utilization": "no_label_extraction",
    "system_memory_utilization": "no_label_extraction",
}


@dataclass(frozen=True)
class GeneratedMappingRule:
    semantic_family: str
    canonical_metric_name: str
    preferred_openconfig_path: str | None
    preferred_openconfig_source: str | None
    preferred_openconfig_module: str | None
    value_transform: str
    label_extractor: str
    fallback_order: list[str]
    openconfig_candidates: list[dict[str, Any]]
    vendor_candidates: dict[str, list[dict[str, Any]]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MetricMappingGenerator:
    def __init__(self, canonical_equivalence_path: Path) -> None:
        self.canonical_equivalence_path = canonical_equivalence_path

    def build(self) -> dict[str, Any]:
        LOG.info(
            "Loading canonical equivalence from %s",
            self.canonical_equivalence_path,
        )
        payload = json.loads(
            self.canonical_equivalence_path.read_text(encoding="utf_8")
        )

        families = payload["semantic_families"]
        generated_rules: dict[str, GeneratedMappingRule] = {}

        for semantic_family, family_data in families.items():
            canonical_metric_name = SEMANTIC_TO_CANONICAL_METRIC.get(
                semantic_family
            )
            if not canonical_metric_name:
                LOG.info(
                    "Skipping semantic family without metric mapping "
                    "target: %s",
                    semantic_family,
                )
                continue

            value_transform = SEMANTIC_TO_VALUE_TRANSFORM.get(
                semantic_family,
                "identity_transform",
            )
            label_extractor = SEMANTIC_TO_LABEL_EXTRACTOR.get(
                semantic_family,
                "no_label_extraction",
            )

            generated_rules[semantic_family] = GeneratedMappingRule(
                semantic_family=semantic_family,
                canonical_metric_name=canonical_metric_name,
                preferred_openconfig_path=family_data.get(
                    "preferred_openconfig"
                ),
                preferred_openconfig_source=family_data.get(
                    "preferred_openconfig_source"
                ),
                preferred_openconfig_module=family_data.get(
                    "preferred_openconfig_module"
                ),
                value_transform=value_transform,
                label_extractor=label_extractor,
                fallback_order=family_data.get("fallback_order", []),
                openconfig_candidates=family_data.get(
                    "openconfig_candidates",
                    [],
                ),
                vendor_candidates=family_data.get("vendor_candidates", {}),
            )

        output = {
            "generated_from": str(self.canonical_equivalence_path),
            "total_metric_families": len(generated_rules),
            "mappings": {
                family: rule.to_dict()
                for family, rule in sorted(generated_rules.items())
            },
        }
        return output


def write_output(output: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf_8")
    LOG.info("Wrote generated metric mappings to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    repo_root = Path(__file__).resolve().parents[2]
    canonical_equivalence_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "canonical_equivalence.json"
    )
    output_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "generated_metric_mappings.json"
    )

    LOG.info("Starting generated metric mapping build")
    generator = MetricMappingGenerator(
        canonical_equivalence_path=canonical_equivalence_path
    )
    output = generator.build()
    write_output(output, output_path)


if __name__ == "__main__":
    main()
