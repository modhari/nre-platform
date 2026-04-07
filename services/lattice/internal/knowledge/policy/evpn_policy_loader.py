from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class EVPNPolicyBundle:
    scenario_tool_policy: dict[str, Any]
    tool_capability_policy: dict[str, Any]
    risk_policy: dict[str, Any]
    vendor_overrides: dict[str, Any]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing policy file: {path}")
    data = yaml.safe_load(path.read_text())
    return data or {}


def load_evpn_policy_bundle(base_dir: str | Path) -> EVPNPolicyBundle:
    base = Path(base_dir)
    return EVPNPolicyBundle(
        scenario_tool_policy=_load_yaml(base / "scenario_tool_policy.yaml"),
        tool_capability_policy=_load_yaml(base / "tool_capability_policy.yaml"),
        risk_policy=_load_yaml(base / "risk_policy.yaml"),
        vendor_overrides=_load_yaml(base / "vendor_overrides.yaml"),
    )
