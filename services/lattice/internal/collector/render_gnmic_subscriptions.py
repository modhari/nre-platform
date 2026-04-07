from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class GnmicSubscriptionEntry:
    """
    One concrete subscription entry that gnmic can use.

    The profile name is preserved so stacked collection remains visible
    in all later rendered artifacts.
    """

    name: str
    path: str
    semantic_family: str
    profile_name: str
    mode: str = "stream"
    stream_mode: str = "sample"
    sample_interval: str = "30s"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GnmicRenderedConfig:
    """
    Minimal gnmic style rendered config artifact.

    In addition to the flat subscription list, this keeps a profile to
    subscription index so later renderers can emit grouped config.
    """

    target: str
    vendor: str
    subscriptions: list[GnmicSubscriptionEntry] = field(
        default_factory=list
    )
    profile_groups: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "vendor": self.vendor,
            "subscriptions": [
                subscription.to_dict()
                for subscription in self.subscriptions
            ],
            "profile_groups": self.profile_groups,
        }


class GnmicSubscriptionRenderer:
    """
    Renders a device subscription plan into a gnmic friendly artifact.

    Current behavior:
    - one rendered subscription per selected path
    - deduplicates identical paths
    - preserves semantic and profile metadata for traceability
    """

    def __init__(self, device_subscription_plan_path: Path) -> None:
        self.device_subscription_plan_path = device_subscription_plan_path

    def build(self) -> dict[str, Any]:
        LOG.info(
            "Loading device subscription plan from %s",
            self.device_subscription_plan_path,
        )
        payload = json.loads(
            self.device_subscription_plan_path.read_text(
                encoding="utf_8"
            )
        )

        profile = payload["device_profile"]
        subscriptions = payload["subscriptions"]

        target = profile["device"]
        vendor = profile["vendor"]

        rendered = GnmicRenderedConfig(
            target=target,
            vendor=vendor,
        )

        seen_paths: set[str] = set()

        for record in subscriptions:
            path = record["path"]

            # Deduplicate exact path repeats so the rendered artifact
            # stays clean even if multiple planning layers converge.
            if path in seen_paths:
                continue
            seen_paths.add(path)

            subscription_name = self._build_subscription_name(
                profile_name=record["profile_name"],
                semantic_family=record["semantic_family"],
            )

            rendered.subscriptions.append(
                GnmicSubscriptionEntry(
                    name=subscription_name,
                    path=path,
                    semantic_family=record["semantic_family"],
                    profile_name=record["profile_name"],
                    mode="stream",
                    stream_mode="sample",
                    sample_interval=self._sample_interval_for_family(
                        record["semantic_family"]
                    ),
                )
            )

            rendered.profile_groups.setdefault(
                record["profile_name"],
                [],
            ).append(subscription_name)

        output = {
            "generated_from": str(self.device_subscription_plan_path),
            "target": target,
            "vendor": vendor,
            "subscription_count": len(rendered.subscriptions),
            "gnmic_config": rendered.to_dict(),
        }
        return output

    def _build_subscription_name(
        self,
        profile_name: str,
        semantic_family: str,
    ) -> str:
        """
        Create a stable, human readable subscription name.
        """
        return f"{profile_name}__{semantic_family}"

    def _sample_interval_for_family(self, semantic_family: str) -> str:
        """
        Family aware sample interval policy.
        """
        if semantic_family in {
            "interface_admin_status",
            "interface_oper_status",
            "bgp_session_state",
        }:
            return "15s"

        if semantic_family in {
            "interface_in_octets",
            "interface_out_octets",
        }:
            return "30s"

        if semantic_family in {
            "bgp_prefixes_received",
            "bgp_prefixes_sent",
        }:
            return "60s"

        return "30s"


def write_output(output: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf_8")
    LOG.info("Wrote gnmic subscription artifact to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    repo_root = Path(__file__).resolve().parents[2]
    device_subscription_plan_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "device_subscription_plan.json"
    )
    output_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "gnmic_leaf_01_subscriptions.json"
    )

    LOG.info("Starting gnmic subscription rendering")
    renderer = GnmicSubscriptionRenderer(
        device_subscription_plan_path=device_subscription_plan_path
    )
    output = renderer.build()
    write_output(output, output_path)


if __name__ == "__main__":
    main()
