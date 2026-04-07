from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


PREFERRED_FULL_PATH_SUFFIXES: dict[str, tuple[str, ...]] = {
    "interface_admin_status": (
        "/interfaces/interface/state/admin-status",
        "/interfaces/interface/config/enabled",
        "/interfaces-state/interface/admin-status",
        "/interfaces/interface/state/admin-state",
    ),
    "interface_oper_status": (
        "/interfaces/interface/state/oper-status",
        "/interfaces-state/interface/oper-status",
        "/interfaces/interface/state/oper-state",
    ),
    "interface_in_octets": (
        "/interfaces/interface/state/counters/in-octets",
        "/interfaces-state/interface/statistics/in-octets",
        "/interfaces/interface/state/statistics/in-octets",
        "/interfaces/interface/state/statistics/input-bytes",
    ),
    "interface_out_octets": (
        "/interfaces/interface/state/counters/out-octets",
        "/interfaces-state/interface/statistics/out-octets",
        "/interfaces/interface/state/statistics/out-octets",
        "/interfaces/interface/state/statistics/output-bytes",
    ),
    "bgp_session_state": (
        "/network-instances/network-instance/protocols/protocol/"
        "bgp/neighbors/neighbor/state/session-state",
        "/network-instances/network-instance/protocols/protocol/"
        "bgp/neighbors/neighbor/state/peer-state",
        "/bgp/neighbors/neighbor/state/session-state",
        "/bgp/neighbors/neighbor/state/peer-state",
        "/bgp/neighbors/neighbor/session-state",
        "/bgp/neighbors/neighbor/peer-state",
    ),
    "bgp_prefixes_received": (
        "/network-instances/network-instance/protocols/protocol/"
        "bgp/neighbors/neighbor/state/prefixes/received",
        "/network-instances/network-instance/protocols/protocol/"
        "bgp/neighbors/neighbor/afi-safis/afi-safi/"
        "state/prefixes/received",
        "/bgp/neighbors/neighbor/state/received-prefixes",
        "/bgp/neighbors/neighbor/received-prefixes",
    ),
    "bgp_prefixes_sent": (
        "/network-instances/network-instance/protocols/protocol/"
        "bgp/neighbors/neighbor/state/prefixes/sent",
        "/network-instances/network-instance/protocols/protocol/"
        "bgp/neighbors/neighbor/afi-safis/afi-safi/"
        "state/prefixes/sent",
        "/bgp/neighbors/neighbor/state/sent-prefixes",
        "/bgp/neighbors/neighbor/sent-prefixes",
    ),
}


REQUIRED_ANCHORS: dict[str, tuple[str, ...]] = {
    "interface_admin_status": ("/interface",),
    "interface_oper_status": ("/interface",),
    "interface_in_octets": ("/interface",),
    "interface_out_octets": ("/interface",),
    "bgp_session_state": ("/bgp",),
    "bgp_prefixes_received": ("/bgp",),
    "bgp_prefixes_sent": ("/bgp",),
}


EXCLUDED_ANCHORS: dict[str, tuple[str, ...]] = {
    "interface_admin_status": (
        "/mpls",
        "/ldp",
        "/ipsec",
        "/macsec",
        "/threshold",
        "/acl",
        "/qos",
        "/pm/",
        "/service",
    ),
    "interface_oper_status": (
        "/actn/",
        "/service",
        "/ipsec",
        "/macsec",
        "/threshold",
        "/pm/",
    ),
    "interface_in_octets": (
        "/ipsec",
        "/macsec",
        "/threshold",
        "/pm/",
        "/service",
        "/qos",
        "/policy",
    ),
    "interface_out_octets": (
        "/ipsec",
        "/macsec",
        "/threshold",
        "/pm/",
        "/service",
        "/qos",
        "/policy",
    ),
    "bgp_session_state": (
        "/messages/",
        "/message/",
        "/error/",
        "/capability/",
        "/transport/",
        "/timers/",
        "/graceful-restart/",
        "/bfd/",
    ),
    "bgp_prefixes_received": (
        "/messages/",
        "/message/",
        "/error/",
        "/capability/",
        "/transport/",
    ),
    "bgp_prefixes_sent": (
        "/messages/",
        "/message/",
        "/error/",
        "/capability/",
        "/transport/",
    ),
}


SOURCE_PRIORITY: dict[str, int] = {
    "openconfig_public": 0,
    "juniper_openconfig": 1,
    "nokia_openconfig": 1,
    "arista_openconfig": 1,
    "juniper_native": 2,
    "arista_native": 2,
    "yangmodels_catalog": 3,
}


# This is the practical bridge until we build full grouping and use
# expansion. It turns grouping local OpenConfig BGP fragments into
# executable full paths.
SYNTHETIC_OPENCONFIG_PATHS: dict[str, dict[str, str]] = {
    "bgp_session_state": {
        "source_name": "openconfig_public",
        "module_name": "openconfig-bgp-neighbor",
        "path": (
            "/network-instances/network-instance/protocols/protocol/"
            "bgp/neighbors/neighbor/state/session-state"
        ),
    },
    "bgp_prefixes_received": {
        "source_name": "openconfig_public",
        "module_name": "openconfig-bgp-neighbor",
        "path": (
            "/network-instances/network-instance/protocols/protocol/"
            "bgp/neighbors/neighbor/state/prefixes/received"
        ),
    },
    "bgp_prefixes_sent": {
        "source_name": "openconfig_public",
        "module_name": "openconfig-bgp-neighbor",
        "path": (
            "/network-instances/network-instance/protocols/protocol/"
            "bgp/neighbors/neighbor/state/prefixes/sent"
        ),
    },
}


def source_priority(source_name: str) -> int:
    return SOURCE_PRIORITY.get(source_name, 99)


class ExactCollectionPathGenerator:
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

        results: dict[str, Any] = {}

        for family, family_data in families.items():
            exact = self._build_family_exact_paths(
                family,
                family_data,
            )
            results[family] = exact

        return {
            "generated_from": str(self.canonical_equivalence_path),
            "exact_collection_paths": dict(sorted(results.items())),
        }

    def _build_family_exact_paths(
        self,
        family: str,
        family_data: dict[str, Any],
    ) -> dict[str, Any]:
        preferred_suffixes = PREFERRED_FULL_PATH_SUFFIXES.get(family, ())
        openconfig_candidates = self._filter_candidates(
            family,
            family_data.get("openconfig_candidates", []),
        )
        vendor_candidates = family_data.get("vendor_candidates", {})

        selected_openconfig = self._pick_best_candidate(
            family,
            openconfig_candidates,
            preferred_suffixes,
        )

        if selected_openconfig is None and family in SYNTHETIC_OPENCONFIG_PATHS:
            synthetic = SYNTHETIC_OPENCONFIG_PATHS[family]
            selected_openconfig = {
                "vendor": "openconfig",
                "source_name": synthetic["source_name"],
                "module_name": synthetic["module_name"],
                "file_path": "",
                "path": synthetic["path"],
                "node_kind": "leaf",
                "leaf_type": None,
                "config_class": "state",
                "semantic_domain": "bgp",
            }

        selected_vendor: dict[str, dict[str, Any] | None] = {}
        for vendor, candidates in vendor_candidates.items():
            filtered = self._filter_candidates(family, candidates)
            selected_vendor[vendor] = self._pick_best_candidate(
                family,
                filtered,
                preferred_suffixes,
            )

        return {
            "preferred_openconfig": selected_openconfig,
            "vendor_fallbacks": dict(sorted(selected_vendor.items())),
        }

    def _filter_candidates(
        self,
        family: str,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        required = REQUIRED_ANCHORS.get(family, ())
        excluded = EXCLUDED_ANCHORS.get(family, ())

        filtered: list[dict[str, Any]] = []
        for candidate in candidates:
            path = candidate["path"].lower()
            node_kind = candidate.get("node_kind", "").lower()
            config_class = candidate.get("config_class", "").lower()

            if node_kind not in {"leaf", "leaf-list"}:
                continue

            if required and not all(anchor in path for anchor in required):
                continue

            if excluded and any(anchor in path for anchor in excluded):
                continue

            if (
                family.startswith("interface_")
                and config_class
                not in {"state", "config", "inherit", "unknown"}
            ):
                continue

            if family.startswith("bgp_"):
                # For BGP, allow both full neighbor paths and grouping local
                # BGP paths.
                if "/bgp" not in path:
                    continue

            filtered.append(candidate)

        return filtered

    def _pick_best_candidate(
        self,
        family: str,
        candidates: list[dict[str, Any]],
        preferred_suffixes: tuple[str, ...],
    ) -> dict[str, Any] | None:
        del family

        if not candidates:
            return None

        def candidate_score(
            candidate: dict[str, Any],
        ) -> tuple[int, int, int, int, str]:
            path = candidate["path"]
            suffix_rank = self._suffix_rank(path, preferred_suffixes)
            src_rank = source_priority(candidate["source_name"])
            depth_score = -path.count("/")
            config_bonus = (
                0 if candidate.get("config_class") == "state" else 1
            )
            return (
                suffix_rank,
                src_rank,
                config_bonus,
                depth_score,
                path,
            )

        ranked = sorted(candidates, key=candidate_score)
        return ranked[0]

    def _suffix_rank(self, path: str, suffixes: tuple[str, ...]) -> int:
        for idx, suffix in enumerate(suffixes):
            if path.endswith(suffix):
                return idx
        return 999


def write_output(output: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf_8")
    LOG.info("Wrote exact collection paths to %s", output_path)


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
        / "exact_collection_paths.json"
    )

    LOG.info("Starting exact collection path generation")
    generator = ExactCollectionPathGenerator(
        canonical_equivalence_path
    )
    output = generator.build()
    write_output(output, output_path)


if __name__ == "__main__":
    main()
