from __future__ import annotations

from dataclasses import dataclass

from internal.enrichment.metric_adapter import (
    MetricAdapter,
    PrometheusMetricRecord,
    RichMetricRecord,
)
from internal.metrics.normalizer import MetricNormalizer, RawMetricInput


@dataclass
class MetricService:
    """
    End to end metric processing service.

    Flow:
    raw input -> normalization -> enrichment -> exporter ready record
    """

    normalizer: MetricNormalizer
    adapter: MetricAdapter

    def process_to_prometheus(
        self,
        raw: RawMetricInput,
    ) -> PrometheusMetricRecord:
        normalized = self.normalizer.normalize(raw)
        return self.adapter.to_prometheus_record(normalized)

    def process_to_rich_record(
        self,
        raw: RawMetricInput,
    ) -> RichMetricRecord:
        normalized = self.normalizer.normalize(raw)
        return self.adapter.to_rich_record(normalized)
