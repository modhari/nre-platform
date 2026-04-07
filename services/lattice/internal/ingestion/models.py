from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CollectorUpdate:
    """
    Raw update emitted by a collector before normalization.

    This is the ingestion boundary object. It stays close to what a gNMI
    collector would emit while still being easy to test locally.
    """

    vendor: str
    device: str
    metric_name: str
    value: float | int | str
    timestamp_ms: int | None = None
    interface: str | None = None
    raw_path: str | None = None
    raw_payload: dict[str, Any] | None = None
    extra_labels: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KafkaMessage:
    """
    Canonical record published to Kafka.

    We keep topic, key, and payload explicit so the publisher can stay
    lightweight and reusable.
    """

    topic: str
    key: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PrometheusWriteRecord:
    """
    Prometheus friendly record derived from the enriched metric.

    This can later back remote write, text exposition, or a local bridge.
    """

    name: str
    value: float | int
    labels: dict[str, str]
    timestamp_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IngestionResult:
    """
    Full result of one ingestion pass.

    It includes the normalized metric, enriched metric, Kafka message,
    and Prometheus ready record so one input can feed multiple backends.
    """

    normalized_metric: dict[str, Any]
    enriched_metric: dict[str, Any]
    kafka_messages: list[KafkaMessage] = field(default_factory=list)
    prometheus_record: PrometheusWriteRecord | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "normalized_metric": self.normalized_metric,
            "enriched_metric": self.enriched_metric,
            "kafka_messages": [
                message.to_dict() for message in self.kafka_messages
            ],
            "prometheus_record": (
                self.prometheus_record.to_dict()
                if self.prometheus_record
                else None
            ),
        }
