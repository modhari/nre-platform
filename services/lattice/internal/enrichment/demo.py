from __future__ import annotations

import json

from .models import NormalizedMetric
from .pipeline import EnrichmentPipeline
from .resolver import EnrichmentResolver


def main() -> None:
    resolver = EnrichmentResolver.from_sample_data()

    metric = NormalizedMetric(
        name="lattice_interface_in_octets_total",
        value=182736451,
        labels={
            "device": "leaf-01",
            "interface": "Ethernet3",
            "vendor": "arista",
        },
        timestamp_ms=1711812345000,
    )

    safe_pipeline = EnrichmentPipeline(
        resolver=resolver,
        metric_label_mode="metrics_safe",
    )
    safe_metric = safe_pipeline.enrich_metric(metric)

    rich_pipeline = EnrichmentPipeline(
        resolver=resolver,
        metric_label_mode="rich",
    )
    rich_metric = rich_pipeline.enrich_metric(metric)

    print("METRICS SAFE OUTPUT")
    print(json.dumps(safe_metric.to_prometheus_sample(), indent=2))
    print()
    print("RICH LABEL OUTPUT")
    print(json.dumps(rich_metric.to_prometheus_sample(), indent=2))
    print()
    print("RICH STRUCTURED CONTEXT")
    print(json.dumps(rich_metric.enrichment, indent=2))


if __name__ == "__main__":
    main()
