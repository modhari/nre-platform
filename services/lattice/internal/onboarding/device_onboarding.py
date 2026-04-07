from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from internal.capability.device_profile import DeviceCapabilityProfile
from internal.collector.collector_runtime import CollectorRuntimeBuilder
from internal.collector.device_subscription_plan import DeviceSubscriptionPlanner
from internal.collector.generate_collection_profiles import (
    CollectionProfileGenerator,
)
from internal.collector.render_gnmic_subscriptions import (
    GnmicSubscriptionRenderer,
)
from internal.collector.render_gnmic_target_config import (
    GnmicTargetConfigRenderer,
)
from internal.collector.render_gnmic_yaml import GnmicYamlRenderer
from internal.collector.target_inventory import (
    TargetInventoryRecord,
    load_inventory,
)
from internal.metrics.generate_mappings import MetricMappingGenerator
from internal.schema.canonical_equivalence import CanonicalEquivalenceBuilder
from internal.schema.generate_exact_collection_paths import (
    ExactCollectionPathGenerator,
)
from internal.schema.generate_path_lookup import PathFamilyLookupGenerator
from internal.schema.path_semantics import PathSemanticsBuilder

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class OnboardingDeviceInput:
    """
    Input record for onboarding one device.

    This is the minimum information needed to connect
    inventory,
    capability selection,
    default profile selection,
    and collector rendering.
    """

    device: str
    address: str
    vendor: str
    role: str
    os_name: str
    version: str
    region: str
    datacenter: str
    port: int = 57400
    insecure: bool = False
    skip_verify: bool = True
    encoding: str = "json_ietf"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeviceOnboardingService:
    """
    Orchestrates the full onboarding flow for one device.

    Flow:
    input device
    to inventory update
    to capability profile
    to stacked profile selection
    to device plan
    to gnmic artifacts
    to runtime plan
    """

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.schema_dir = repo_root / "data" / "generated" / "schema"
        self.schema_dir.mkdir(parents=True, exist_ok=True)

    def onboard(self, device_input: OnboardingDeviceInput) -> dict[str, Any]:
        LOG.info("Starting onboarding for device %s", device_input.device)

        # Make sure all prerequisite generated artifacts exist.
        # This is important because generated data is intentionally not
        # checked into git.
        self._ensure_prerequisites()

        inventory_path = self.schema_dir / "target_inventory.json"
        capability_profile_path = (
            self.schema_dir / "device_capability_profile.json"
        )
        device_subscription_plan_path = (
            self.schema_dir / "device_subscription_plan.json"
        )
        gnmic_subscriptions_path = (
            self.schema_dir / "gnmic_leaf_01_subscriptions.json"
        )
        gnmic_target_config_path = (
            self.schema_dir / "gnmic_leaf_01_target_config.json"
        )
        gnmic_yaml_path = (
            self.schema_dir / "gnmic_leaf_01_target_config.yaml"
        )
        runtime_plan_path = (
            self.schema_dir / "collector_runtime_plan.json"
        )

        self._update_inventory(
            inventory_path=inventory_path,
            device_input=device_input,
        )

        capability_profile = self._build_capability_profile(device_input)
        self._write_json(
            capability_profile_path,
            capability_profile.to_dict(),
        )

        selected_profiles = self._select_profiles_for_role(
            device_input.role
        )

        planner = DeviceSubscriptionPlanner(
            collection_profiles_path=(
                self.schema_dir / "collection_profiles.json"
            ),
            exact_collection_paths_path=(
                self.schema_dir / "exact_collection_paths.json"
            ),
        )
        device_plan = planner.build_plan(
            profile=capability_profile,
            selected_profiles=selected_profiles,
        )
        self._write_json(device_subscription_plan_path, device_plan)

        subscription_renderer = GnmicSubscriptionRenderer(
            device_subscription_plan_path=device_subscription_plan_path
        )
        gnmic_subscriptions = subscription_renderer.build()
        self._write_json(gnmic_subscriptions_path, gnmic_subscriptions)

        target_config_renderer = GnmicTargetConfigRenderer(
            subscription_artifact_path=gnmic_subscriptions_path,
            target_inventory_path=inventory_path,
        )
        gnmic_target_config = target_config_renderer.build()
        self._write_json(gnmic_target_config_path, gnmic_target_config)

        yaml_renderer = GnmicYamlRenderer(
            gnmic_target_config_path=gnmic_target_config_path
        )
        yaml_text = yaml_renderer.build_yaml()
        gnmic_yaml_path.write_text(yaml_text, encoding="utf_8")

        runtime_builder = CollectorRuntimeBuilder(
            gnmic_target_config_path=gnmic_target_config_path,
            gnmic_yaml_path=gnmic_yaml_path,
        )
        runtime_plan = runtime_builder.build()
        self._write_json(runtime_plan_path, runtime_plan)

        return {
            "device_input": device_input.to_dict(),
            "selected_profiles": selected_profiles,
            "artifacts": {
                "inventory": str(inventory_path),
                "capability_profile": str(capability_profile_path),
                "device_subscription_plan": str(
                    device_subscription_plan_path
                ),
                "gnmic_subscriptions": str(gnmic_subscriptions_path),
                "gnmic_target_config": str(gnmic_target_config_path),
                "gnmic_yaml": str(gnmic_yaml_path),
                "runtime_plan": str(runtime_plan_path),
            },
        }

    def _ensure_prerequisites(self) -> None:
        """
        Regenerate prerequisite schema artifacts when they are missing.

        Generated artifacts are intentionally excluded from git, so onboarding
        must be able to rebuild the minimum dependency chain locally.
        """
        path_index_path = self.schema_dir / "path_index.jsonl"
        if not path_index_path.exists():
            raise FileNotFoundError(
                "Missing prerequisite path index at "
                f"{path_index_path}. Generate it first with "
                "python3 -m internal.schema.path_index"
            )

        path_semantics_path = self.schema_dir / "path_semantics.json"
        if not path_semantics_path.exists():
            LOG.info("Bootstrapping path semantics")
            builder = PathSemanticsBuilder(path_index_path=path_index_path)
            self._write_json(path_semantics_path, builder.build())

        canonical_equivalence_path = (
            self.schema_dir / "canonical_equivalence.json"
        )
        if not canonical_equivalence_path.exists():
            LOG.info("Bootstrapping canonical equivalence")
            builder = CanonicalEquivalenceBuilder(
                path_semantics_path=path_semantics_path
            )
            self._write_json(canonical_equivalence_path, builder.build())

        generated_metric_mappings_path = (
            self.schema_dir / "generated_metric_mappings.json"
        )
        if not generated_metric_mappings_path.exists():
            LOG.info("Bootstrapping generated metric mappings")
            generator = MetricMappingGenerator(
                canonical_equivalence_path=canonical_equivalence_path
            )
            self._write_json(
                generated_metric_mappings_path,
                generator.build(),
            )

        path_family_lookup_path = (
            self.schema_dir / "path_family_lookup.json"
        )
        if not path_family_lookup_path.exists():
            LOG.info("Bootstrapping path family lookup")
            generator = PathFamilyLookupGenerator(
                path_semantics_path=path_semantics_path
            )
            self._write_json(path_family_lookup_path, generator.build())

        exact_collection_paths_path = (
            self.schema_dir / "exact_collection_paths.json"
        )
        if not exact_collection_paths_path.exists():
            LOG.info("Bootstrapping exact collection paths")
            generator = ExactCollectionPathGenerator(
                canonical_equivalence_path=canonical_equivalence_path
            )
            self._write_json(
                exact_collection_paths_path,
                generator.build(),
            )

        collection_profiles_path = (
            self.schema_dir / "collection_profiles.json"
        )
        if not collection_profiles_path.exists():
            LOG.info("Bootstrapping collection profiles")
            generator = CollectionProfileGenerator()
            self._write_json(collection_profiles_path, generator.build())

    def _update_inventory(
        self,
        inventory_path: Path,
        device_input: OnboardingDeviceInput,
    ) -> None:
        """
        Update or create the target inventory entry for the new device.
        """
        if inventory_path.exists():
            inventory = load_inventory(inventory_path)
            targets = {
                device: record.to_dict()
                for device, record in inventory.records.items()
            }
        else:
            targets = {}

        targets[device_input.device] = TargetInventoryRecord(
            device=device_input.device,
            address=device_input.address,
            port=device_input.port,
            vendor=device_input.vendor,
            os_name=device_input.os_name,
            region=device_input.region,
            datacenter=device_input.datacenter,
            insecure=device_input.insecure,
            skip_verify=device_input.skip_verify,
            encoding=device_input.encoding,
        ).to_dict()

        self._write_json(inventory_path, {"targets": targets})

    def _build_capability_profile(
        self,
        device_input: OnboardingDeviceInput,
    ) -> DeviceCapabilityProfile:
        """
        Build a first pass capability profile from vendor and role.

        This is intentionally simple.
        Later this can become version aware and inventory backed.
        """
        openconfig_supported_families = [
            "interface_admin_status",
            "interface_oper_status",
            "interface_in_octets",
            "interface_out_octets",
            "bgp_prefixes_received",
            "bgp_prefixes_sent",
        ]
        native_required_families: list[str] = []

        # Keep current Juniper BGP session state on native fallback because
        # that path is already proven in the exact path selection stage.
        if device_input.vendor == "juniper":
            native_required_families.append("bgp_session_state")
        else:
            openconfig_supported_families.append("bgp_session_state")

        return DeviceCapabilityProfile(
            device=device_input.device,
            vendor=device_input.vendor,
            role=device_input.role,
            os_name=device_input.os_name,
            version=device_input.version,
            openconfig_supported_families=openconfig_supported_families,
            native_required_families=native_required_families,
        )

    def _select_profiles_for_role(self, role: str) -> list[str]:
        """
        Choose default stacked collection profiles by role.

        This keeps onboarding opinionated and simple.
        """
        normalized_role = role.lower()

        if normalized_role in {"leaf", "spine", "superspine"}:
            return ["health", "traffic", "debug"]

        if normalized_role in {"border", "edge", "edge_leaf"}:
            return ["health", "traffic", "debug"]

        return ["health", "traffic"]

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf_8")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    repo_root = Path(__file__).resolve().parents[2]

    # Sample onboarding input.
    # Later this can come from Netconfig, NetBox, or an API request.
    device_input = OnboardingDeviceInput(
        device="leaf-01",
        address="10.10.10.11",
        vendor="juniper",
        role="leaf",
        os_name="junos",
        version="24.2R1",
        region="us-west",
        datacenter="sjc1",
    )

    service = DeviceOnboardingService(repo_root=repo_root)
    result = service.onboard(device_input=device_input)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
