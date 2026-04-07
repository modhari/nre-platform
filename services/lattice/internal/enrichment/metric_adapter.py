from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import EnrichedMetric, NormalizedMetric
from .pipeline import EnrichmentPipeline


@dataclass(frozen=True)
class PrometheusMetricRecord:
    name: str
    value: float | int
    labels: dict[str, str]
    timestamp_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "labels": self.labels,
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass(frozen=True)
class RichMetricRecord:
    name: str
    value: float | int
    labels: dict[str, str]
    timestamp_ms: int | None
    enrichment: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "labels": self.labels,
            "timestamp_ms": self.timestamp_ms,
            "enrichment": self.enrichment,
        }


class MetricAdapter:
    def __init__(self, pipeline: EnrichmentPipeline) -> None:
        self.pipeline = pipeline

    def to_prometheus_record(
        self,
        metric: NormalizedMetric,
    ) -> PrometheusMetricRecord:
        enriched = self._enrich(metric, mode="metrics_safe")
        return PrometheusMetricRecord(
            name=enriched.name,
            value=enriched.value,
            labels=enriched.labels,
            timestamp_ms=enriched.timestamp_ms,
        )

    def to_rich_record(
        self,
        metric: NormalizedMetric,
    ) -> RichMetricRecord:
        enriched = self._enrich(metric, mode="rich")
        return RichMetricRecord(
            name=enriched.name,
            value=enriched.value,
            labels=enriched.labels,
            timestamp_ms=enriched.timestamp_ms,
            enrichment=enriched.enrichment,
        )

    def _enrich(
        self,
        metric: NormalizedMetric,
        mode: str,
    ) -> EnrichedMetric:
        return self.pipeline.enrich_metric(metric, mode=mode)
