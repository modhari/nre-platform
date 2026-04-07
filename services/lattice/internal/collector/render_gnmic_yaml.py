from __future__ import annotations

import json
import logging
from pathlib import Path

LOG = logging.getLogger(__name__)


class GnmicYamlRenderer:
    """
    Render a gnmic style YAML config from the generated JSON target config.

    This version preserves stacked collection profile grouping so the
    final YAML clearly shows:
    - health subscriptions
    - traffic subscriptions
    - debug subscriptions
    """

    def __init__(self, gnmic_target_config_path: Path) -> None:
        self.gnmic_target_config_path = gnmic_target_config_path

    def build_yaml(self) -> str:
        LOG.info(
            "Loading gnmic target config from %s",
            self.gnmic_target_config_path,
        )
        payload = json.loads(
            self.gnmic_target_config_path.read_text(encoding="utf_8")
        )

        config = payload["gnmic_target_config"]
        encoding = config["encoding"]
        targets = config["targets"]
        subscriptions = config["subscriptions"]
        bindings = config["target_bindings"]
        profile_groups = config.get("profile_groups", {})

        lines: list[str] = []

        lines.append(f"encoding: {encoding}")
        lines.append("")

        lines.append("targets:")
        for target_name, target in targets.items():
            lines.append(f"  {target_name}:")
            lines.append(f"    address: {target['address']}")
            lines.append(f"    username: {target['username']}")
            lines.append(f"    password: {target['password']}")
            lines.append(
                f"    insecure: {str(target['insecure']).lower()}"
            )
            lines.append(
                f"    skip-verify: {str(target['skip_verify']).lower()}"
            )
        lines.append("")

        # Render subscriptions grouped by stacked collection profile first.
        # This makes the final YAML much easier to read and operate.
        lines.append("subscriptions:")
        for profile_name, subscription_names in profile_groups.items():
            lines.append(f"  # profile: {profile_name}")
            for subscription_name in subscription_names:
                subscription = subscriptions[subscription_name]
                lines.append(f"  {subscription_name}:")
                lines.append(f"    mode: {subscription['mode']}")
                lines.append(
                    f"    stream-mode: {subscription['stream_mode']}"
                )
                lines.append(
                    f"    sample-interval: "
                    f"{subscription['sample_interval']}"
                )
                lines.append("    paths:")
                lines.append(f"      - {subscription['path']}")
                lines.append(
                    f"    # semantic-family: "
                    f"{subscription['semantic_family']}"
                )
                lines.append(
                    f"    # profile-name: {subscription['profile_name']}"
                )
            lines.append("")

        lines.append("target-subscriptions:")
        for target_name, subscription_names in bindings.items():
            lines.append(f"  {target_name}:")
            for subscription_name in subscription_names:
                lines.append(f"    - {subscription_name}")
        lines.append("")

        # Also render a profile grouping section explicitly so operators
        # can see which subscriptions belong to each stacked collection tier.
        lines.append("profile-subscriptions:")
        for profile_name, subscription_names in profile_groups.items():
            lines.append(f"  {profile_name}:")
            for subscription_name in subscription_names:
                lines.append(f"    - {subscription_name}")
        lines.append("")

        return "\n".join(lines)


def write_output(yaml_text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_text, encoding="utf_8")
    LOG.info("Wrote gnmic YAML config to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    repo_root = Path(__file__).resolve().parents[2]
    gnmic_target_config_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "gnmic_leaf_01_target_config.json"
    )
    output_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "gnmic_leaf_01_target_config.yaml"
    )

    LOG.info("Starting gnmic YAML rendering")
    renderer = GnmicYamlRenderer(
        gnmic_target_config_path=gnmic_target_config_path
    )
    yaml_text = renderer.build_yaml()
    write_output(yaml_text, output_path)


if __name__ == "__main__":
    main()
