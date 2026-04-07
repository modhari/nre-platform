from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollectionProfile:
    """
    A stacked collection profile.

    Each profile groups semantic families that belong together operationally.
    This lets Lattice build different collection bundles for:
    - fast health signals
    - steady traffic visibility
    - deeper debug coverage
    """

    name: str
    description: str
    semantic_families: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CollectionProfileGenerator:
    """
    Generates the first set of stacked collection profiles.

    These are intentionally simple and human readable.
    Later we can make them role aware, platform aware, or scenario aware.
    """

    def build(self) -> dict[str, Any]:
        profiles = {
            "health": CollectionProfile(
                name="health",
                description="Fast operational health signals for interfaces and protocol state.",
                semantic_families=[
                    "interface_admin_status",
                    "interface_oper_status",
                    "bgp_session_state",
                ],
            ),
            "traffic": CollectionProfile(
                name="traffic",
                description="Steady state traffic counters for throughput visibility.",
                semantic_families=[
                    "interface_in_octets",
                    "interface_out_octets",
                ],
            ),
            "debug": CollectionProfile(
                name="debug",
                description="Deeper optional protocol visibility for troubleshooting.",
                semantic_families=[
                    "bgp_prefixes_received",
                    "bgp_prefixes_sent",
                ],
            ),
        }

        return {
            "profiles": {
                name: profile.to_dict()
                for name, profile in sorted(profiles.items())
            }
        }


def write_output(output: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf_8")
    LOG.info("Wrote collection profiles to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    repo_root = Path(__file__).resolve().parents[2]
    output_path = repo_root / "data" / "generated" / "schema" / "collection_profiles.json"

    LOG.info("Starting collection profile generation")
    generator = CollectionProfileGenerator()
    output = generator.build()
    write_output(output, output_path)


if __name__ == "__main__":
    main()
