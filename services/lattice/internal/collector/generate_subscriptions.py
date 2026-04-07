from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


INTENT_TO_SEMANTIC_FAMILIES: dict[str, list[str]] = {
    "interface_health": [
        "interface_admin_status",
        "interface_oper_status",
    ],
    "interface_traffic": [
        "interface_in_octets",
        "interface_out_octets",
    ],
    "bgp_health": [
        "bgp_session_state",
    ],
    "bgp_volume": [
        "bgp_prefixes_received",
        "bgp_prefixes_sent",
    ],
}


@dataclass(frozen=True)
class SubscriptionCandidate:
    semantic_family: str
    vendor: str
    source_name: str
    module_name: str
    path: str
    priority: int
    selection_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IntentSubscriptionPlan:
    intent_name: str
    semantic_families: list[str]
    preferred_openconfig: list[SubscriptionCandidate] = field(
        default_factory=list
    )
    vendor_fallbacks: dict[str, list[SubscriptionCandidate]] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_name": self.intent_name,
            "semantic_families": self.semantic_families,
            "preferred_openconfig": [
                candidate.to_dict()
                for candidate in self.preferred_openconfig
            ],
            "vendor_fallbacks": {
                vendor: [candidate.to_dict() for candidate in candidates]
                for vendor, candidates in self.vendor_fallbacks.items()
            },
        }


class SubscriptionGenerator:
    def __init__(
        self,
        canonical_equivalence_path: Path,
        generated_metric_mappings_path: Path,
    ) -> None:
        self.canonical_equivalence_path = canonical_equivalence_path
        self.generated_metric_mappings_path = generated_metric_mappings_path

    def build(self) -> dict[str, Any]:
        LOG.info(
            "Loading canonical equivalence from %s",
            self.canonical_equivalence_path,
        )
        canonical_payload = json.loads(
            self.canonical_equivalence_path.read_text(encoding="utf_8")
        )

        LOG.info(
            "Loading generated metric mappings from %s",
            self.generated_metric_mappings_path,
        )
        mappings_payload = json.loads(
            self.generated_metric_mappings_path.read_text(
                encoding="utf_8"
            )
        )

        canonical_families = canonical_payload["semantic_families"]
        metric_mappings = mappings_payload["mappings"]

        plans: dict[str, IntentSubscriptionPlan] = {}

        for intent_name, semantic_families in (
            INTENT_TO_SEMANTIC_FAMILIES.items()
        ):
            preferred_openconfig: list[SubscriptionCandidate] = []
            vendor_fallbacks: dict[str, list[SubscriptionCandidate]] = {}

            for family in semantic_families:
                canonical_family = canonical_families.get(family)
                if not canonical_family:
                    LOG.info(
                        "Skipping missing canonical family for intent %s "
                        "family %s",
                        intent_name,
                        family,
                    )
                    continue

                metric_mapping = metric_mappings.get(family)
                if not metric_mapping:
                    LOG.info(
                        "Skipping missing metric mapping for intent %s "
                        "family %s",
                        intent_name,
                        family,
                    )
                    continue

                openconfig_path = canonical_family.get(
                    "preferred_openconfig"
                )
                if openconfig_path:
                    preferred_openconfig.append(
                        SubscriptionCandidate(
                            semantic_family=family,
                            vendor="openconfig",
                            source_name=(
                                canonical_family.get(
                                    "preferred_openconfig_source"
                                )
                                or "openconfig"
                            ),
                            module_name=(
                                canonical_family.get(
                                    "preferred_openconfig_module"
                                )
                                or ""
                            ),
                            path=openconfig_path,
                            priority=0,
                            selection_reason="preferred_openconfig",
                        )
                    )

                vendor_candidates = canonical_family.get(
                    "vendor_candidates",
                    {},
                )
                for vendor, candidates in vendor_candidates.items():
                    deduped_paths: set[str] = set()
                    selected_candidates: list[SubscriptionCandidate] = []

                    for idx, candidate in enumerate(candidates):
                        path = candidate["path"]
                        if path == openconfig_path:
                            continue
                        if path in deduped_paths:
                            continue
                        deduped_paths.add(path)

                        selected_candidates.append(
                            SubscriptionCandidate(
                                semantic_family=family,
                                vendor=vendor,
                                source_name=candidate["source_name"],
                                module_name=candidate["module_name"],
                                path=path,
                                priority=idx + 1,
                                selection_reason="vendor_fallback",
                            )
                        )

                    if selected_candidates:
                        vendor_fallbacks.setdefault(vendor, []).extend(
                            selected_candidates
                        )

            plans[intent_name] = IntentSubscriptionPlan(
                intent_name=intent_name,
                semantic_families=semantic_families,
                preferred_openconfig=preferred_openconfig,
                vendor_fallbacks={
                    k: v for k, v in sorted(vendor_fallbacks.items())
                },
            )

        output = {
            "generated_from": {
                "canonical_equivalence": str(
                    self.canonical_equivalence_path
                ),
                "generated_metric_mappings": str(
                    self.generated_metric_mappings_path
                ),
            },
            "intent_plans": {
                intent_name: plan.to_dict()
                for intent_name, plan in sorted(plans.items())
            },
        }
        return output


def write_output(output: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf_8")
    LOG.info("Wrote subscription plans to %s", output_path)


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
    generated_metric_mappings_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "generated_metric_mappings.json"
    )
    output_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "subscription_plans.json"
    )

    LOG.info("Starting subscription generation")
    generator = SubscriptionGenerator(
        canonical_equivalence_path=canonical_equivalence_path,
        generated_metric_mappings_path=generated_metric_mappings_path,
    )
    output = generator.build()
    write_output(output, output_path)


if __name__ == "__main__":
    main()
