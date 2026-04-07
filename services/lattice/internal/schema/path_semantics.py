from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


SEMANTIC_RULES: dict[str, tuple[str, ...]] = {
    "interface_in_octets": (
        "/in-octets",
        "/input-bytes",
        "/in-octet",
    ),
    "interface_out_octets": (
        "/out-octets",
        "/output-bytes",
        "/out-octet",
    ),
    "interface_oper_status": (
        "/oper-status",
        "/oper-state",
        "/oper-state-name",
    ),
    "interface_admin_status": (
        "/admin-status",
        "/admin-state",
        "/enabled",
    ),
    "interface_in_errors": (
        "/in-errors",
        "/input-errors",
    ),
    "interface_out_errors": (
        "/out-errors",
        "/output-errors",
    ),
    "bgp_session_state": (
        "/session-state",
        "/peer-state",
        "/connection-state",
    ),
    "bgp_prefixes_received": (
        "/prefixes/received",
        "/received-prefixes",
        "/accepted-prefixes",
    ),
    "bgp_prefixes_sent": (
        "/prefixes/sent",
        "/sent-prefixes",
        "/advertised-prefixes",
    ),
    "optics_rx_power": (
        "/rx-power",
        "/input-power",
        "/received-optical-power",
    ),
    "optics_tx_power": (
        "/tx-power",
        "/output-power",
        "/transmit-power",
    ),
    "system_cpu_utilization": (
        "/cpu-utilization",
        "/cpu/usage",
        "/cpu/total",
    ),
    "system_memory_utilization": (
        "/memory-utilization",
        "/memory/usage",
        "/memory/used-percent",
    ),
}


@dataclass(frozen=True)
class SemanticPathRecord:
    semantic_family: str
    vendor: str
    source_name: str
    module_name: str
    file_path: str
    path: str
    node_name: str
    node_kind: str
    parent_path: str | None
    leaf_type: str | None
    list_keys: list[str]
    config_class: str
    semantic_domain: str
    module_prefix: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PathSemanticsBuilder:
    def __init__(self, path_index_path: Path) -> None:
        self.path_index_path = path_index_path

    def build(self) -> dict[str, Any]:
        LOG.info("Loading path index from %s", self.path_index_path)

        grouped: dict[str, list[SemanticPathRecord]] = defaultdict(list)
        total_paths = 0
        matched_paths = 0

        with self.path_index_path.open("r", encoding="utf_8") as fh:
            for idx, line in enumerate(fh, start=1):
                if idx == 1 or idx % 500000 == 0:
                    LOG.info("Processed %s path records", idx)

                total_paths += 1
                payload = json.loads(line)

                semantic_family = self._classify(payload)
                if not semantic_family:
                    continue

                matched_paths += 1
                grouped[semantic_family].append(
                    SemanticPathRecord(
                        semantic_family=semantic_family,
                        vendor=payload["vendor"],
                        source_name=payload["source_name"],
                        module_name=payload["module_name"],
                        file_path=payload["file_path"],
                        path=payload["path"],
                        node_name=payload["node_name"],
                        node_kind=payload["node_kind"],
                        parent_path=payload.get("parent_path"),
                        leaf_type=payload.get("leaf_type"),
                        list_keys=payload.get("list_keys", []),
                        config_class=payload.get("config_class", "unknown"),
                        semantic_domain=payload.get(
                            "semantic_domain",
                            "misc",
                        ),
                        module_prefix=payload.get("module_prefix"),
                    )
                )

        LOG.info(
            "Completed semantic grouping: matched %s of %s paths",
            matched_paths,
            total_paths,
        )

        summary = self._build_summary(grouped)

        output = {
            "generated_from": str(self.path_index_path),
            "total_paths_scanned": total_paths,
            "total_paths_matched": matched_paths,
            "semantic_families": {
                family: [record.to_dict() for record in records]
                for family, records in grouped.items()
            },
            "summary": summary,
        }
        return output

    def _classify(self, payload: dict[str, Any]) -> str | None:
        path = payload.get("path", "").lower()
        semantic_domain = payload.get("semantic_domain", "").lower()
        node_kind = payload.get("node_kind", "").lower()

        if node_kind not in {"leaf", "leaf-list"}:
            return None

        for family, patterns in SEMANTIC_RULES.items():
            if any(pattern in path for pattern in patterns):
                if (
                    family.startswith("interface_")
                    and semantic_domain != "interfaces"
                ):
                    continue
                if (
                    family.startswith("bgp_")
                    and semantic_domain
                    not in {"bgp", "routing", "network_instance"}
                ):
                    continue
                if (
                    family.startswith("optics_")
                    and semantic_domain not in {"optics", "platform"}
                ):
                    continue
                if (
                    family.startswith("system_")
                    and semantic_domain != "system"
                ):
                    continue
                return family

        return None

    def _build_summary(
        self,
        grouped: dict[str, list[SemanticPathRecord]],
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {}

        for family, records in grouped.items():
            vendors = sorted({record.vendor for record in records})
            modules = sorted({record.module_name for record in records})
            sources = sorted({record.source_name for record in records})

            summary[family] = {
                "count": len(records),
                "vendors": vendors,
                "sources": sources,
                "sample_modules": modules[:25],
            }

        return dict(sorted(summary.items()))


def write_output(output: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf_8")
    LOG.info("Wrote path semantics to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    repo_root = Path(__file__).resolve().parents[2]
    path_index_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "path_index.jsonl"
    )
    output_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "path_semantics.json"
    )

    LOG.info("Starting path semantics build")
    builder = PathSemanticsBuilder(path_index_path=path_index_path)
    output = builder.build()
    write_output(output, output_path)


if __name__ == "__main__":
    main()
