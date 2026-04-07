from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GeneratedMetricMapping:
    semantic_family: str
    canonical_metric_name: str
    preferred_openconfig_path: str | None
    preferred_openconfig_source: str | None
    preferred_openconfig_module: str | None
    value_transform: str
    label_extractor: str
    fallback_order: list[str]
    openconfig_candidates: list[dict[str, Any]]
    vendor_candidates: dict[str, list[dict[str, Any]]]


class GeneratedMetricMappingLoader:
    def __init__(self, mapping_path: Path) -> None:
        self.mapping_path = mapping_path
        self._mappings_by_family: dict[str, GeneratedMetricMapping] = {}
        self._loaded = False

    def load(self) -> None:
        payload = json.loads(self.mapping_path.read_text(encoding="utf_8"))
        mappings = payload.get("mappings", {})

        loaded: dict[str, GeneratedMetricMapping] = {}
        for family, rule in mappings.items():
            loaded[family] = GeneratedMetricMapping(
                semantic_family=rule["semantic_family"],
                canonical_metric_name=rule["canonical_metric_name"],
                preferred_openconfig_path=rule.get("preferred_openconfig_path"),
                preferred_openconfig_source=rule.get("preferred_openconfig_source"),
                preferred_openconfig_module=rule.get("preferred_openconfig_module"),
                value_transform=rule.get("value_transform", "identity_transform"),
                label_extractor=rule.get("label_extractor", "no_label_extraction"),
                fallback_order=rule.get("fallback_order", []),
                openconfig_candidates=rule.get("openconfig_candidates", []),
                vendor_candidates=rule.get("vendor_candidates", {}),
            )

        self._mappings_by_family = loaded
        self._loaded = True

    def get(self, semantic_family: str) -> GeneratedMetricMapping | None:
        if not self._loaded:
            self.load()
        return self._mappings_by_family.get(semantic_family)

    def all(self) -> dict[str, GeneratedMetricMapping]:
        if not self._loaded:
            self.load()
        return dict(self._mappings_by_family)
