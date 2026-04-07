from __future__ import annotations

import json
from pathlib import Path

from internal.enrichment.adapter_demo import build_sample_providers
from internal.enrichment.metric_adapter import MetricAdapter
from internal.enrichment.pipeline import EnrichmentPipeline
from internal.enrichment.resolver import EnrichmentResolver
from internal.metrics.normalizer import MetricNormalizer, RawMetricInput
from internal.metrics.service import MetricService


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    generated_mapping_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "generated_metric_mappings.json"
    )
    path_family_lookup_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "path_family_lookup.json"
    )

    providers = build_sample_providers()
    resolver = EnrichmentResolver(providers=providers)
    pipeline = EnrichmentPipeline(resolver=resolver)
    adapter = MetricAdapter(pipeline=pipeline)
    normalizer = MetricNormalizer(
        generated_mapping_path=generated_mapping_path,
        path_family_lookup_path=path_family_lookup_path,
    )

    service = MetricService(
        normalizer=normalizer,
        adapter=adapter,
    )

    raw_inputs = [
        RawMetricInput(
            vendor="arista",
            device="leaf-01",
            metric_name="interfaces.in_octets",
            value=182736451,
            timestamp_ms=1711812345000,
            raw_path=(
                "/interfaces/interface[name=Ethernet3]/state/"
                "counters/in-octets"
            ),
            raw_payload=None,
        ),
        RawMetricInput(
            vendor="juniper",
            device="leaf-01",
            metric_name="interfaces.oper_status",
            value="up",
            timestamp_ms=1711812345001,
            raw_path=(
                "/interfaces/interface[name=Ethernet3]/state/oper-status"
            ),
            raw_payload=None,
        ),
        RawMetricInput(
            vendor="juniper",
            device="leaf-01",
            metric_name="bgp.session_state",
            value="established",
            timestamp_ms=1711812345002,
            raw_path=(
                "/network-instances/network-instance[name=default]/"
                "protocols/protocol/bgp/neighbors/"
                "neighbor[neighbor-address=10.0.0.1]/state/session-state"
            ),
            raw_payload=None,
            extra_labels={"protocol": "bgp"},
        ),
    ]

    for raw_metric in raw_inputs:
        prom_record = service.process_to_prometheus(raw_metric)
        rich_record = service.process_to_rich_record(raw_metric)

        print("RAW INPUT")
        print(json.dumps(raw_metric.__dict__, indent=2))
        print()
        print("PROMETHEUS RECORD")
        print(json.dumps(prom_record.to_dict(), indent=2))
        print()
        print("RICH RECORD")
        print(json.dumps(rich_record.to_dict(), indent=2))
        print()
        print("=" * 80)
        print()


if __name__ == "__main__":
    main()
