from __future__ import annotations

from typing import Dict

from gnmi_collection_agent.core.types import CapabilityProfile


def build_capability_profile(device_id: str, models: Dict[str, str]) -> CapabilityProfile:
    supports_openconfig = any("openconfig" in k.lower() for k in models.keys())
    origins = {"openconfig": "openconfig"} if supports_openconfig else {}
    return CapabilityProfile(
        device_id=device_id,
        supports_openconfig=supports_openconfig,
        supported_models=dict(models),
        origins=origins,
    )
