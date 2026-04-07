from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TargetInventoryRecord:
    """
    Inventory record for one telemetry target.

    This is intentionally small for the first pass.
    It gives the renderer enough information to build a collector config
    without hardcoding addresses in the rendering layer.
    """

    device: str
    address: str
    port: int = 57400
    vendor: str | None = None
    os_name: str | None = None
    region: str | None = None
    datacenter: str | None = None
    insecure: bool = False
    skip_verify: bool = True
    encoding: str = "json_ietf"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TargetInventory:
    """
    Simple inventory abstraction.

    Later this can be backed by:
    - Netconfig
    - NetBox
    - service discovery
    - database snapshots
    """

    def __init__(self, records: dict[str, TargetInventoryRecord]) -> None:
        self.records = records

    def get(self, device: str) -> TargetInventoryRecord | None:
        return self.records.get(device)


def build_sample_inventory() -> TargetInventory:
    return TargetInventory(
        records={
            "leaf-01": TargetInventoryRecord(
                device="leaf-01",
                address="10.10.10.11",
                port=57400,
                vendor="juniper",
                os_name="junos",
                region="us-west",
                datacenter="sjc1",
                insecure=False,
                skip_verify=True,
                encoding="json_ietf",
            ),
        }
    )


def write_sample_inventory(output_path: Path) -> None:
    inventory = build_sample_inventory()
    payload = {
        "targets": {
            device: record.to_dict()
            for device, record in inventory.records.items()
        }
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf_8")


def load_inventory(input_path: Path) -> TargetInventory:
    payload = json.loads(input_path.read_text(encoding="utf_8"))
    records: dict[str, TargetInventoryRecord] = {}

    for device, record in payload.get("targets", {}).items():
        records[device] = TargetInventoryRecord(
            device=record["device"],
            address=record["address"],
            port=record.get("port", 57400),
            vendor=record.get("vendor"),
            os_name=record.get("os_name"),
            region=record.get("region"),
            datacenter=record.get("datacenter"),
            insecure=record.get("insecure", False),
            skip_verify=record.get("skip_verify", True),
            encoding=record.get("encoding", "json_ietf"),
        )

    return TargetInventory(records=records)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    output_path = repo_root / "data" / "generated" / "schema" / "target_inventory.json"
    write_sample_inventory(output_path)


if __name__ == "__main__":
    main()
