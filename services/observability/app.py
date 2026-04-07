"""
app.py — Kafka → InfluxDB writer for NRE observability.

Responsibilities:
  - Consume events from the nre.incidents and nre.plans Kafka topics.
  - Transform each event into an InfluxDB point with tags and fields.
  - Write points to InfluxDB using the synchronous write API.

InfluxDB measurements written:
  nre_incidents — one point per incident_snapshot event
    tags:   fabric, device, root_cause, approval_required
    fields: safe_action_count, gated_action_count,
            suppressed_action_count, execution_enabled, payload_json

  nre_plans — one point per plan_snapshot event
    tags:   fabric, device, root_cause, approval_required
    fields: safe_step_count, gated_step_count,
            skipped_action_count, execution_enabled, payload_json

Environment variables (all required):
  KAFKA_BOOTSTRAP_SERVERS   e.g. kafka:9092
  KAFKA_TOPICS              comma-separated, e.g. nre.incidents,nre.plans
  INFLUXDB_URL              e.g. http://influxdb:8086
  INFLUXDB_TOKEN            admin token set at InfluxDB init time
  INFLUXDB_ORG              e.g. nre
  INFLUXDB_BUCKET           e.g. nre
"""
from __future__ import annotations

import json
import os

from kafka import KafkaConsumer
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


# ── Configuration from environment ───────────────────────────────────────────

KAFKA_BOOTSTRAP_SERVERS = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"
)
KAFKA_TOPICS = os.environ.get(
    "KAFKA_TOPICS", "nre.incidents,nre.plans"
).split(",")

INFLUXDB_URL    = os.environ["INFLUXDB_URL"]
INFLUXDB_TOKEN  = os.environ["INFLUXDB_TOKEN"]
INFLUXDB_ORG    = os.environ["INFLUXDB_ORG"]
INFLUXDB_BUCKET = os.environ["INFLUXDB_BUCKET"]


# ── Event → InfluxDB point transformation ────────────────────────────────────

def _to_bool_str(value: object) -> str:
    """Convert any truthy value to the string true or false."""
    return "true" if bool(value) else "false"


def build_point(event: dict) -> Point | None:
    """
    Transform one NRE event dict into an InfluxDB Point.

    Returns None for unknown event_type values — those events are
    silently dropped rather than crashing the writer loop.

    Tag values are low-cardinality strings used for Grafana filtering.
    Field values are numeric or string measurements for charting.
    """
    payload    = event.get("payload", {})
    event_type = event.get("event_type")

    if event_type == "incident_snapshot":
        # ── Incident: tag with fabric/device/root_cause for Grafana ──────────
        return (
            Point("nre_incidents")
            .tag("fabric",            event.get("fabric",     "unknown"))
            .tag("device",            event.get("device",     "unknown"))
            .tag("root_cause",        event.get("root_cause", "unknown"))
            .tag("approval_required", _to_bool_str(
                payload.get("approval_required", False)
            ))
            # ── Action count fields for trend charts ──────────────────────────
            .field("safe_action_count",
                   len(payload.get("safe_actions", [])))
            .field("gated_action_count",
                   len(payload.get("gated_actions", [])))
            .field("suppressed_action_count",
                   len(payload.get("suppressed_actions", [])))
            .field("execution_enabled",
                   payload.get("execution_enabled", False))
            # ── Full payload JSON for drill-down queries ───────────────────────
            .field("payload_json", json.dumps(event))
            .time(event.get("ts"), WritePrecision.NS)
        )

    elif event_type == "plan_snapshot":
        # ── Plan: tag with fabric/device/root_cause for Grafana ──────────────
        return (
            Point("nre_plans")
            .tag("fabric",            event.get("fabric",     "unknown"))
            .tag("device",            event.get("device",     "unknown"))
            .tag("root_cause",        event.get("root_cause", "unknown"))
            .tag("approval_required", _to_bool_str(
                payload.get("approval_required", False)
            ))
            # ── Step count fields ─────────────────────────────────────────────
            .field("safe_step_count",
                   len(payload.get("safe_steps", [])))
            .field("gated_step_count",
                   len(payload.get("gated_steps", [])))
            .field("skipped_action_count",
                   len(payload.get("skipped_actions", [])))
            .field("execution_enabled",
                   payload.get("execution_enabled", False))
            .field("payload_json", json.dumps(event))
            .time(event.get("ts"), WritePrecision.NS)
        )

    # ── Unknown event type — drop silently ────────────────────────────────────
    print(
        f"[kafka_influx_writer] unknown event_type={event_type!r} — skipped"
    )
    return None


# ── Main consumer loop ────────────────────────────────────────────────────────

def main() -> None:
    """
    Connect to Kafka and InfluxDB then consume and write events forever.

    auto_offset_reset=earliest ensures events published before the writer
    pod starts are not lost — useful after a crash or restart.
    """
    # ── Kafka consumer ────────────────────────────────────────────────────────
    consumer = KafkaConsumer(
        *[t.strip() for t in KAFKA_TOPICS],
        bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS],
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        group_id="kafka_influx_writer",
    )

    # ── InfluxDB client ───────────────────────────────────────────────────────
    influx    = InfluxDBClient(
        url=INFLUXDB_URL,
        token=INFLUXDB_TOKEN,
        org=INFLUXDB_ORG,
    )
    write_api = influx.write_api(write_options=SYNCHRONOUS)

    print(
        f"[kafka_influx_writer] started — "
        f"topics={KAFKA_TOPICS} influxdb={INFLUXDB_URL}",
        flush=True,
    )

    # ── Event loop ────────────────────────────────────────────────────────────
    for msg in consumer:
        event = msg.value

        point = build_point(event)
        if point is None:
            continue

        write_api.write(
            bucket=INFLUXDB_BUCKET,
            org=INFLUXDB_ORG,
            record=point,
        )

        print(
            f"[kafka_influx_writer] wrote "
            f"event_type={event.get('event_type')} "
            f"incident_id={event.get('incident_id')}",
            flush=True,
        )


if __name__ == "__main__":
    main()
