from __future__ import annotations

from .models import EnrichedMetric, EnrichmentKey, LabelMode, NormalizedMetric
from .resolver import EnrichmentResolver


class EnrichmentPipeline:
    def __init__(
        self,
        resolver: EnrichmentResolver,
        metric_label_mode: LabelMode = "metrics_safe",
    ) -> None:
        self.resolver = resolver
        self.metric_label_mode = metric_label_mode

    def enrich_metric(
        self,
        metric: NormalizedMetric,
        mode: LabelMode | None = None,
    ) -> EnrichedMetric:
        key = EnrichmentKey(
            device=metric.labels.get("device", ""),
            interface=metric.labels.get("interface"),
            subinterface=metric.labels.get("subinterface"),
            lag=metric.labels.get("lag"),
            network_instance=metric.labels.get("network_instance"),
            circuit_id=metric.labels.get("circuit_id"),
            customer_attachment_id=metric.labels.get("customer_attachment_id"),
        )

        enrichment = self.resolver.resolve(key)

        effective_mode = mode or self.metric_label_mode

        merged_labels = dict(metric.labels)
        merged_labels.update(enrichment.to_flat_labels(mode=effective_mode))

        return EnrichedMetric(
            name=metric.name,
            value=metric.value,
            labels=merged_labels,
            timestamp_ms=metric.timestamp_ms,
            enrichment=enrichment.to_rich_context(),
        )
