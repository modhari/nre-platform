from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DeviceCapabilityProfile:
    device: str
    vendor: str
    role: str
    os_name: str | None = None
    version: str | None = None
    openconfig_supported_families: list[str] = field(default_factory=list)
    native_required_families: list[str] = field(default_factory=list)

    def supports_openconfig(self, semantic_family: str) -> bool:
        return semantic_family in self.openconfig_supported_families

    def requires_native(self, semantic_family: str) -> bool:
        return semantic_family in self.native_required_families

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_device_capability_profile(
    profile: DeviceCapabilityProfile,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf_8")


def load_device_capability_profile(input_path: Path) -> DeviceCapabilityProfile:
    payload = json.loads(input_path.read_text(encoding="utf_8"))
    return DeviceCapabilityProfile(
        device=payload["device"],
        vendor=payload["vendor"],
        role=payload["role"],
        os_name=payload.get("os_name"),
        version=payload.get("version"),
        openconfig_supported_families=payload.get("openconfig_supported_families", []),
        native_required_families=payload.get("native_required_families", []),
    )


def build_sample_profile() -> DeviceCapabilityProfile:
    return DeviceCapabilityProfile(
        device="leaf-01",
        vendor="juniper",
        role="leaf",
        os_name="junos",
        version="24.2R1",
        openconfig_supported_families=[
            "interface_admin_status",
            "interface_oper_status",
            "interface_in_octets",
            "interface_out_octets",
        ],
        native_required_families=[
            "bgp_session_state",
        ],
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    output_path = repo_root / "data" / "generated" / "schema" / "device_capability_profile.json"
    profile = build_sample_profile()
    write_device_capability_profile(profile, output_path)


if __name__ == "__main__":
    main()
