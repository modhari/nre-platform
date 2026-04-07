from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from internal.capability.device_profile import (
    DeviceCapabilityProfile,
    load_device_capability_profile,
)

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceSubscriptionRecord:
    """
    One selected subscription for a specific device.

    This record preserves:
    - which profile requested it
    - which semantic family it belongs to
    - which exact path was selected
    - whether the choice came from OpenConfig or vendor fallback
    """

    profile_name: str
    semantic_family: str
    path: str
    source_name: str
    module_name: str
    selection: str
    priority: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeviceSubscriptionPlanner:
    """
    Build a device specific subscription plan from stacked collection profiles.

    Flow:
    - load collection profiles
    - expand selected profiles into semantic families
    - use exact collection paths
    - apply device capability aware selection
    """

    def __init__(
        self,
        collection_profiles_path: Path,
        exact_collection_paths_path: Path,
    ) -> None:
        self.collection_profiles_path = collection_profiles_path
        self.exact_collection_paths_path = exact_collection_paths_path

    def build_plan(
        self,
        profile: DeviceCapabilityProfile,
        selected_profiles: list[str],
    ) -> dict[str, Any]:
        LOG.info(
            "Loading collection profiles from %s",
            self.collection_profiles_path,
        )
        profiles_payload = json.loads(
            self.collection_profiles_path.read_text(encoding="utf_8")
        )
        collection_profiles = profiles_payload["profiles"]

        LOG.info(
            "Loading exact collection paths from %s",
            self.exact_collection_paths_path,
        )
        exact_payload = json.loads(
            self.exact_collection_paths_path.read_text(encoding="utf_8")
        )
        exact_paths = exact_payload["exact_collection_paths"]

        selected_records: list[DeviceSubscriptionRecord] = []

        for profile_name in selected_profiles:
            collection_profile = collection_profiles.get(profile_name)
            if not collection_profile:
                LOG.info(
                    "Skipping missing collection profile %s",
                    profile_name,
                )
                continue

            semantic_families = collection_profile.get("semantic_families", [])
            selected_records.extend(
                self._select_for_profile(
                    profile_name=profile_name,
                    semantic_families=semantic_families,
                    device_profile=profile,
                    exact_paths=exact_paths,
                )
            )

        output = {
            "device_profile": profile.to_dict(),
            "selected_profiles": selected_profiles,
            "subscription_count": len(selected_records),
            "subscriptions": [
                record.to_dict() for record in selected_records
            ],
        }
        return output

    def _select_for_profile(
        self,
        profile_name: str,
        semantic_families: list[str],
        device_profile: DeviceCapabilityProfile,
        exact_paths: dict[str, Any],
    ) -> list[DeviceSubscriptionRecord]:
        records: list[DeviceSubscriptionRecord] = []

        for family in semantic_families:
            family_exact = exact_paths.get(family, {})
            preferred_openconfig = family_exact.get("preferred_openconfig")
            vendor_fallbacks = family_exact.get("vendor_fallbacks", {})
            vendor_candidate = vendor_fallbacks.get(device_profile.vendor)

            # Prefer OpenConfig only when this specific device advertises
            # support for the semantic family.
            use_openconfig = (
                device_profile.supports_openconfig(family)
                and preferred_openconfig is not None
            )

            # Force native fallback when the device profile says the family
            # must be collected using native models.
            use_native = (
                device_profile.requires_native(family)
                and vendor_candidate is not None
            )

            if use_openconfig:
                records.append(
                    DeviceSubscriptionRecord(
                        profile_name=profile_name,
                        semantic_family=family,
                        path=preferred_openconfig["path"],
                        source_name=preferred_openconfig["source_name"],
                        module_name=preferred_openconfig["module_name"],
                        selection="preferred_openconfig",
                        priority=0,
                    )
                )
                continue

            if use_native:
                records.append(
                    DeviceSubscriptionRecord(
                        profile_name=profile_name,
                        semantic_family=family,
                        path=vendor_candidate["path"],
                        source_name=vendor_candidate["source_name"],
                        module_name=vendor_candidate["module_name"],
                        selection="vendor_fallback",
                        priority=1,
                    )
                )
                continue

            # Safe default behavior:
            # if the device did not explicitly require native and there is a
            # usable OpenConfig path, choose it.
            if preferred_openconfig is not None:
                records.append(
                    DeviceSubscriptionRecord(
                        profile_name=profile_name,
                        semantic_family=family,
                        path=preferred_openconfig["path"],
                        source_name=preferred_openconfig["source_name"],
                        module_name=preferred_openconfig["module_name"],
                        selection="preferred_openconfig_default",
                        priority=0,
                    )
                )
                continue

            if vendor_candidate is not None:
                records.append(
                    DeviceSubscriptionRecord(
                        profile_name=profile_name,
                        semantic_family=family,
                        path=vendor_candidate["path"],
                        source_name=vendor_candidate["source_name"],
                        module_name=vendor_candidate["module_name"],
                        selection="vendor_fallback_default",
                        priority=1,
                    )
                )

        return records


def write_output(output: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf_8")
    LOG.info("Wrote device subscription plan to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    repo_root = Path(__file__).resolve().parents[2]
    collection_profiles_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "collection_profiles.json"
    )
    exact_collection_paths_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "exact_collection_paths.json"
    )
    capability_profile_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "device_capability_profile.json"
    )
    output_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "device_subscription_plan.json"
    )

    device_profile = load_device_capability_profile(capability_profile_path)

    # Stacked collection selection:
    # health and traffic are enabled by default here.
    # debug can be added when deeper protocol visibility is needed.
    selected_profiles = [
        "health",
        "traffic",
        "debug",
    ]

    LOG.info("Starting capability aware device subscription planning")
    planner = DeviceSubscriptionPlanner(
        collection_profiles_path=collection_profiles_path,
        exact_collection_paths_path=exact_collection_paths_path,
    )
    output = planner.build_plan(
        profile=device_profile,
        selected_profiles=selected_profiles,
    )
    write_output(output, output_path)


if __name__ == "__main__":
    main()
