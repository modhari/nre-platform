from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from pathlib import Path

from internal.enrichment.adapter_demo import build_sample_providers
from internal.enrichment.metric_adapter import MetricAdapter
from internal.enrichment.pipeline import EnrichmentPipeline
from internal.enrichment.resolver import EnrichmentResolver
from internal.ingestion.kafka_publisher import InMemoryKafkaPublisher
from internal.ingestion.models import (
    CollectorUpdate,
    IngestionResult,
    KafkaMessage,
    PrometheusWriteRecord,
)
from internal.ingestion.prometheus_writer import PrometheusTextWriter
from internal.ingestion.topic_router import topic_for_metric_name
from internal.metrics.normalizer import MetricNormalizer, RawMetricInput

LOG = logging.getLogger(__name__)


def _to_serializable_dict(obj):
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if is_dataclass(obj):
        return asdict(obj)
    raise TypeError(f"Unsupported object for serialization: {type(obj)!r}")


class CollectorIngestionService:
    """
    Ingestion bridge for raw collector output.

    Flow:
    raw collector update
    to metric normalization
    to enrichment
    to Kafka publish
    to Prometheus ready record
    """

    def __init__(
        self,
        normalizer: MetricNormalizer,
        adapter: MetricAdapter,
        kafka_publisher: InMemoryKafkaPublisher,
    ) -> None:
        self.normalizer = normalizer
        self.adapter = adapter
        self.kafka_publisher = kafka_publisher

    def ingest(self, update: CollectorUpdate) -> IngestionResult:
        raw_metric = RawMetricInput(
            vendor=update.vendor,
            device=update.device,
            metric_name=update.metric_name,
            value=update.value,
            interface=update.interface,
            timestamp_ms=update.timestamp_ms,
            extra_labels=update.extra_labels,
            raw_path=update.raw_path,
            raw_payload=update.raw_payload,
        )

        normalized_metric = self.normalizer.normalize(raw_metric)

        # Build both rich and Prometheus safe views from the same normalized
        # canonical metric so downstream consumers can choose the format they need.
        rich_record = self.adapter.to_rich_record(normalized_metric)
        prometheus_view = self.adapter.to_prometheus_record(normalized_metric)

        kafka_messages = self._build_kafka_messages(rich_record)
        for message in kafka_messages:
            self.kafka_publisher.publish(message)

        prometheus_record = PrometheusWriteRecord(
            name=prometheus_view.name,
            value=prometheus_view.value,
            labels=prometheus_view.labels,
            timestamp_ms=prometheus_view.timestamp_ms,
        )

        return IngestionResult(
            normalized_metric=_to_serializable_dict(normalized_metric),
            enriched_metric=_to_serializable_dict(rich_record),
            kafka_messages=kafka_messages,
            prometheus_record=prometheus_record,
        )

    def _build_kafka_messages(self, rich_record) -> list[KafkaMessage]:
        topic = topic_for_metric_name(rich_record.name)
        key = self._build_message_key(rich_record.labels)

        message = KafkaMessage(
            topic=topic,
            key=key,
            payload=_to_serializable_dict(rich_record),
        )
        return [message]

    def _build_message_key(self, labels: dict[str, str]) -> str:
        device = labels.get("device", "unknown")
        interface = labels.get("interface")
        peer = labels.get("peer")

        if interface:
            return f"{device}:{interface}"

        if peer:
            return f"{device}:{peer}"

        return device


def build_default_ingestion_service(
    repo_root: Path,
) -> CollectorIngestionService:
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
    kafka_publisher = InMemoryKafkaPublisher()

    return CollectorIngestionService(
        normalizer=normalizer,
        adapter=adapter,
        kafka_publisher=kafka_publisher,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    repo_root = Path(__file__).resolve().parents[2]
    service = build_default_ingestion_service(repo_root)

    update = CollectorUpdate(
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
        extra_labels={"protocol": "bgp"},
    )

    result = service.ingest(update)

    print("INGESTION RESULT")
    print(json.dumps(result.to_dict(), indent=2))
    print()
    print("KAFKA MESSAGES")
    print(service.kafka_publisher.dump_json())

    if result.prometheus_record:
        writer = PrometheusTextWriter()
        exposition = writer.render_records([result.prometheus_record])

        output_path = (
            repo_root
            / "data"
            / "generated"
            / "ingestion"
            / "prometheus_sample.prom"
        )
        writer.write_records([result.prometheus_record], output_path)

        print()
        print("PROMETHEUS EXPOSITION")
        print(exposition)
        print(f"WROTE: {output_path}")


if __name__ == "__main__":
    main()
