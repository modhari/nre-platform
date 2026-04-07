from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from internal.enrichment.models import NormalizedMetric
from internal.metrics.generated_mapping_loader import (
    GeneratedMetricMappingLoader,
)
from internal.metrics.mappings import (
    MetricMappingRegistry,
    bgp_neighbor_from_payload_or_path,
    bool_up_down_transform,
    default_metric_mapping_registry,
    identity_transform,
    interface_from_payload_or_path,
    network_instance_from_payload_or_path,
    no_label_extraction,
)
from internal.metrics.path_family_lookup_loader import (
    PathFamilyLookupLoader,
)


@dataclass(frozen=True)
class RawMetricInput:
    vendor: str
    device: str
    metric_name: str
    value: float | int | str
    interface: str | None = None
    timestamp_ms: int | None = None
    extra_labels: dict[str, str] | None = None
    raw_path: str | None = None
    raw_payload: dict[str, Any] | None = None


class MetricNormalizationError(ValueError):
    pass


class MetricNormalizer:
    """
    Metric normalizer with three stages:

    1. generated path family lookup plus generated metric mappings
    2. heuristic semantic family fallback plus generated metric mappings
    3. built in fallback registry
    """

    def __init__(
        self,
        mapping_registry: MetricMappingRegistry | None = None,
        generated_mapping_path: Path | None = None,
        path_family_lookup_path: Path | None = None,
    ) -> None:
        self.mapping_registry = (
            mapping_registry or default_metric_mapping_registry()
        )
        self.generated_loader: GeneratedMetricMappingLoader | None = None
        self.path_family_lookup: PathFamilyLookupLoader | None = None

        if generated_mapping_path and generated_mapping_path.exists():
            self.generated_loader = GeneratedMetricMappingLoader(
                generated_mapping_path
            )

        if path_family_lookup_path and path_family_lookup_path.exists():
            self.path_family_lookup = PathFamilyLookupLoader(
                path_family_lookup_path
            )

    def normalize(self, raw: RawMetricInput) -> NormalizedMetric:
        generated_result = self._normalize_with_generated_mappings(raw)
        if generated_result:
            return generated_result

        fallback_rule = self._resolve_rule(raw)
        if not fallback_rule:
            raise MetricNormalizationError(
                f"No metric mapping found for vendor={raw.vendor!r}, "
                f"metric_name={raw.metric_name!r}, raw_path={raw.raw_path!r}"
            )

        normalized_value = fallback_rule.value_transform(raw.value)

        labels: dict[str, str] = {
            "device": raw.device,
            "vendor": raw.vendor,
        }

        extracted_labels = fallback_rule.label_extractor(
            raw.raw_payload,
            raw.raw_path,
        )
        if extracted_labels:
            labels.update(extracted_labels)

        if raw.interface:
            labels["interface"] = raw.interface

        if raw.extra_labels:
            labels.update(raw.extra_labels)

        if fallback_rule.static_labels:
            labels.update(fallback_rule.static_labels)

        return NormalizedMetric(
            name=fallback_rule.canonical_metric_name,
            value=normalized_value,
            labels=labels,
            timestamp_ms=raw.timestamp_ms,
        )

    def _normalize_with_generated_mappings(
        self,
        raw: RawMetricInput,
    ) -> NormalizedMetric | None:
        if not self.generated_loader:
            return None

        semantic_family = self._resolve_semantic_family(raw)
        if not semantic_family:
            return None

        generated_rule = self.generated_loader.get(semantic_family)
        if not generated_rule:
            return None

        value_transform = self._resolve_value_transform(
            generated_rule.value_transform
        )
        label_extractor = self._resolve_label_extractor(
            generated_rule.label_extractor
        )

        normalized_value = value_transform(raw.value)

        labels: dict[str, str] = {
            "device": raw.device,
            "vendor": raw.vendor,
        }

        extracted_labels = label_extractor(raw.raw_payload, raw.raw_path)
        if extracted_labels:
            labels.update(extracted_labels)

        if raw.interface:
            labels["interface"] = raw.interface

        if raw.extra_labels:
            labels.update(raw.extra_labels)

        return NormalizedMetric(
            name=generated_rule.canonical_metric_name,
            value=normalized_value,
            labels=labels,
            timestamp_ms=raw.timestamp_ms,
        )

    def _resolve_semantic_family(
        self,
        raw: RawMetricInput,
    ) -> str | None:
        if self.path_family_lookup:
            family = self.path_family_lookup.lookup_family(raw.raw_path)
            if family:
                return family

        return self._infer_semantic_family(raw)

    def _infer_semantic_family(
        self,
        raw: RawMetricInput,
    ) -> str | None:
        path = (raw.raw_path or "").lower()
        metric_name = (raw.metric_name or "").lower()

        if "in-octets" in path or metric_name == "interfaces.in_octets":
            return "interface_in_octets"

        if "out-octets" in path or metric_name == "interfaces.out_octets":
            return "interface_out_octets"

        if (
            "oper-status" in path
            or "oper-state" in path
            or metric_name == "interfaces.oper_status"
        ):
            return "interface_oper_status"

        if (
            "admin-status" in path
            or "admin-state" in path
            or metric_name == "interfaces.admin_status"
        ):
            return "interface_admin_status"

        if (
            "session-state" in path
            or "peer-state" in path
            or metric_name == "bgp.session_state"
        ):
            return "bgp_session_state"

        if (
            "received-prefixes" in path
            or "accepted-prefixes" in path
            or metric_name == "bgp.prefixes_received"
        ):
            return "bgp_prefixes_received"

        if (
            "sent-prefixes" in path
            or "advertised-prefixes" in path
            or metric_name == "bgp.prefixes_sent"
        ):
            return "bgp_prefixes_sent"

        return None

    def _resolve_value_transform(self, transform_name: str):
        transforms = {
            "identity_transform": identity_transform,
            "bool_up_down_transform": bool_up_down_transform,
        }
        if transform_name not in transforms:
            raise MetricNormalizationError(
                f"Unknown value transform {transform_name!r}"
            )
        return transforms[transform_name]

    def _resolve_label_extractor(self, extractor_name: str):
        def bgp_session_labels_from_payload_or_path(
            payload: dict | None,
            raw_path: str | None,
        ) -> dict[str, str]:
            labels: dict[str, str] = {}
            labels.update(
                network_instance_from_payload_or_path(payload, raw_path)
            )
            labels.update(
                bgp_neighbor_from_payload_or_path(payload, raw_path)
            )
            return labels

        extractors = {
            "no_label_extraction": no_label_extraction,
            "interface_from_payload_or_path": interface_from_payload_or_path,
            "bgp_session_labels_from_payload_or_path": (
                bgp_session_labels_from_payload_or_path
            ),
        }
        if extractor_name not in extractors:
            raise MetricNormalizationError(
                f"Unknown label extractor {extractor_name!r}"
            )
        return extractors[extractor_name]

    def _resolve_rule(self, raw: RawMetricInput):
        vendor_rule = self.mapping_registry.resolve(
            vendor=raw.vendor,
            raw_metric_name=raw.metric_name,
            raw_path=raw.raw_path,
        )
        if vendor_rule:
            return vendor_rule

        shared_rule = self.mapping_registry.resolve(
            vendor="shared",
            raw_metric_name=raw.metric_name,
            raw_path=raw.raw_path,
        )
        if shared_rule:
            return shared_rule

        return None
