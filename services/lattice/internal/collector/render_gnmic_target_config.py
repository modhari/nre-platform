from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from internal.collector.target_inventory import (
    TargetInventoryRecord,
    load_inventory,
)

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class GnmicTarget:
    """
    Minimal target definition for a device.

    Address and connection defaults come from inventory.
    Credentials remain placeholders.
    """

    name: str
    address: str
    username: str
    password: str
    insecure: bool = False
    skip_verify: bool = False


@dataclass(frozen=True)
class GnmicSubscription:
    """
    One gnmic subscription entry.

    Profile metadata is preserved so later YAML rendering can group
    subscriptions into stacked collection layers.
    """

    name: str
    path: str
    mode: str
    stream_mode: str
    sample_interval: str
    semantic_family: str
    profile_name: str


@dataclass
class GnmicTargetConfig:
    """
    Rendered gnmic target config.

    This keeps:
    - global encoding
    - targets
    - named subscriptions
    - target bindings
    - profile groups
    """

    encoding: str
    targets: dict[str, GnmicTarget] = field(default_factory=dict)
    subscriptions: dict[str, GnmicSubscription] = field(
        default_factory=dict
    )
    target_bindings: dict[str, list[str]] = field(default_factory=dict)
    profile_groups: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "encoding": self.encoding,
            "targets": {
                name: asdict(target)
                for name, target in self.targets.items()
            },
            "subscriptions": {
                name: asdict(subscription)
                for name, subscription in self.subscriptions.items()
            },
            "target_bindings": self.target_bindings,
            "profile_groups": self.profile_groups,
        }


class GnmicTargetConfigRenderer:
    """
    Renders a fuller gnmic target config from the subscription artifact.

    Inventory supplies:
    - address
    - port
    - encoding
    - TLS defaults
    """

    def __init__(
        self,
        subscription_artifact_path: Path,
        target_inventory_path: Path,
    ) -> None:
        self.subscription_artifact_path = subscription_artifact_path
        self.target_inventory_path = target_inventory_path

    def build(self) -> dict[str, Any]:
        LOG.info(
            "Loading gnmic subscription artifact from %s",
            self.subscription_artifact_path,
        )
        payload = json.loads(
            self.subscription_artifact_path.read_text(encoding="utf_8")
        )

        LOG.info("Loading target inventory from %s", self.target_inventory_path)
        inventory = load_inventory(self.target_inventory_path)

        target_name = payload["target"]
        vendor = payload["vendor"]
        subscriptions = payload["gnmic_config"]["subscriptions"]
        profile_groups = payload["gnmic_config"].get("profile_groups", {})

        target_record = inventory.get(target_name)
        if not target_record:
            raise ValueError(
                f"No inventory record found for target {target_name!r}"
            )

        rendered = GnmicTargetConfig(encoding=target_record.encoding)
        rendered.targets[target_name] = self._build_target(target_record)

        binding_names: list[str] = []

        for sub in subscriptions:
            subscription_name = sub["name"]
            rendered.subscriptions[subscription_name] = GnmicSubscription(
                name=subscription_name,
                path=sub["path"],
                mode=sub["mode"],
                stream_mode=sub["stream_mode"],
                sample_interval=sub["sample_interval"],
                semantic_family=sub["semantic_family"],
                profile_name=sub["profile_name"],
            )
            binding_names.append(subscription_name)

        rendered.target_bindings[target_name] = binding_names
        rendered.profile_groups = profile_groups

        output = {
            "generated_from": {
                "subscription_artifact": str(
                    self.subscription_artifact_path
                ),
                "target_inventory": str(self.target_inventory_path),
            },
            "target": target_name,
            "vendor": vendor,
            "subscription_count": len(rendered.subscriptions),
            "gnmic_target_config": rendered.to_dict(),
        }
        return output

    def _build_target(
        self,
        target_record: TargetInventoryRecord,
    ) -> GnmicTarget:
        """
        Render one target stanza from inventory.
        """
        return GnmicTarget(
            name=target_record.device,
            address=f"{target_record.address}:{target_record.port}",
            username="REPLACE_ME",
            password="REPLACE_ME",
            insecure=target_record.insecure,
            skip_verify=target_record.skip_verify,
        )


def write_output(output: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf_8")
    LOG.info("Wrote gnmic target config to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    repo_root = Path(__file__).resolve().parents[2]
    subscription_artifact_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "gnmic_leaf_01_subscriptions.json"
    )
    target_inventory_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "target_inventory.json"
    )
    output_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "gnmic_leaf_01_target_config.json"
    )

    LOG.info("Starting gnmic target config rendering")
    renderer = GnmicTargetConfigRenderer(
        subscription_artifact_path=subscription_artifact_path,
        target_inventory_path=target_inventory_path,
    )
    output = renderer.build()
    write_output(output, output_path)


if __name__ == "__main__":
    main()
