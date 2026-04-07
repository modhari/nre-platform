from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from internal.ingestion.models import KafkaMessage

LOG = logging.getLogger(__name__)


@dataclass
class InMemoryKafkaPublisher:
    """
    Simple in memory Kafka publisher for development and testing.

    This keeps Option B moving without requiring a real Kafka cluster yet.
    The same interface can later be backed by confluent kafka or aiokafka.
    """

    published_messages: list[KafkaMessage] = field(default_factory=list)

    def publish(self, message: KafkaMessage) -> None:
        LOG.info(
            "Publishing message to topic=%s key=%s",
            message.topic,
            message.key,
        )
        self.published_messages.append(message)

    def dump_json(self) -> str:
        return json.dumps(
            [message.to_dict() for message in self.published_messages],
            indent=2,
        )
