from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

INTERFACE_NAME_PATTERNS = [
    re.compile(r"\[name=([^\]]+)\]"),
    re.compile(r'"interface"\s*:\s*"([^"]+)"'),
    re.compile(r'"name"\s*:\s*"([^"]+)"'),
]

NEIGHBOR_ADDRESS_PATTERNS = [
    re.compile(r"\[neighbor-address=([^\]]+)\]"),
    re.compile(r'"neighbor"\s*:\s*"([^"]+)"'),
    re.compile(r'"neighbor_address"\s*:\s*"([^"]+)"'),
]

NETWORK_INSTANCE_PATTERNS = [
    re.compile(r"\[name=([^\]]+)\]"),
    re.compile(r'"network_instance"\s*:\s*"([^"]+)"'),
]


def identity_transform(value: float | int | str) -> float | int:
    return value  # type: ignore[return-value]


def bool_up_down_transform(value: float | int | str) -> int:
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"up", "established", "active", "true"}:
            return 1
        if lowered in {"down", "idle", "inactive", "false"}:
            return 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    return 0


def interface_from_payload_or_path(
    payload: dict | None,
    raw_path: str | None,
) -> dict[str, str]:
    labels: dict[str, str] = {}

    if payload:
        for key in ("interface", "name"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                labels["interface"] = value
                return labels

    if raw_path:
        for pattern in INTERFACE_NAME_PATTERNS:
            match = pattern.search(raw_path)
            if match:
                labels["interface"] = match.group(1)
                return labels

    return labels


def network_instance_from_payload_or_path(
    payload: dict | None,
    raw_path: str | None,
) -> dict[str, str]:
    labels: dict[str, str] = {}

    if payload:
        value = payload.get("network_instance")
        if isinstance(value, str) and value:
            labels["network_instance"] = value
            return labels

    if raw_path and "/network-instances/network-instance" in raw_path:
        for pattern in NETWORK_INSTANCE_PATTERNS:
            match = pattern.search(raw_path)
            if match:
                labels["network_instance"] = match.group(1)
                return labels

    return labels


def bgp_neighbor_from_payload_or_path(
    payload: dict | None,
    raw_path: str | None,
) -> dict[str, str]:
    labels: dict[str, str] = {}

    if payload:
        for key in ("peer", "neighbor", "neighbor_address"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                labels["peer"] = value
                return labels

    if raw_path:
        for pattern in NEIGHBOR_ADDRESS_PATTERNS:
            match = pattern.search(raw_path)
            if match:
                labels["peer"] = match.group(1)
                return labels

    return labels


def no_label_extraction(
    payload: dict | None,
    raw_path: str | None,
) -> dict[str, str]:
    del payload, raw_path
    return {}


@dataclass(frozen=True)
class MetricMappingRule:
    canonical_metric_name: str
    raw_metric_name: str | None = None
    raw_path_suffix: str | None = None
    value_transform: Callable[[float | int | str], float | int] = (
        identity_transform
    )
    label_extractor: Callable[
        [dict | None, str | None],
        dict[str, str],
    ] = no_label_extraction
    static_labels: dict[str, str] = field(default_factory=dict)


@dataclass
class MetricMappingRegistry:
    rules_by_vendor: dict[str, list[MetricMappingRule]]

    def resolve(
        self,
        vendor: str,
        raw_metric_name: str,
        raw_path: str | None,
    ) -> MetricMappingRule | None:
        rules = self.rules_by_vendor.get(vendor, [])
        for rule in rules:
            if rule.raw_metric_name and rule.raw_metric_name == raw_metric_name:
                return rule
            if (
                rule.raw_path_suffix
                and raw_path
                and raw_path.endswith(rule.raw_path_suffix)
            ):
                return rule
        return None


def default_metric_mapping_registry() -> MetricMappingRegistry:
    shared_rules = [
        MetricMappingRule(
            canonical_metric_name="lattice_interface_in_octets_total",
            raw_metric_name="interfaces.in_octets",
            raw_path_suffix="/in-octets",
            value_transform=identity_transform,
            label_extractor=interface_from_payload_or_path,
        ),
        MetricMappingRule(
            canonical_metric_name="lattice_interface_out_octets_total",
            raw_metric_name="interfaces.out_octets",
            raw_path_suffix="/out-octets",
            value_transform=identity_transform,
            label_extractor=interface_from_payload_or_path,
        ),
        MetricMappingRule(
            canonical_metric_name="lattice_interface_oper_up",
            raw_metric_name="interfaces.oper_status",
            raw_path_suffix="/oper-status",
            value_transform=bool_up_down_transform,
            label_extractor=interface_from_payload_or_path,
        ),
        MetricMappingRule(
            canonical_metric_name="lattice_interface_admin_up",
            raw_metric_name="interfaces.admin_status",
            raw_path_suffix="/admin-status",
            value_transform=bool_up_down_transform,
            label_extractor=interface_from_payload_or_path,
        ),
        MetricMappingRule(
            canonical_metric_name="lattice_bgp_session_up",
            raw_metric_name="bgp.session_state",
            raw_path_suffix="/session-state",
            value_transform=bool_up_down_transform,
            label_extractor=no_label_extraction,
        ),
    ]

    return MetricMappingRegistry(
        rules_by_vendor={
            "shared": shared_rules,
            "arista": [],
            "juniper": [],
            "nokia": [],
        }
    )
