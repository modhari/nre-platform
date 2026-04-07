from __future__ import annotations

from pathlib import Path

from internal.ingestion.models import PrometheusWriteRecord


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class PrometheusTextWriter:
    """
    Render Prometheus safe records into text exposition format.

    This is a simple bridge for local testing and POP or regional
    integration before adding a full remote write path.
    """

    def render_record(self, record: PrometheusWriteRecord) -> str:
        labels = ""
        if record.labels:
            rendered = ",".join(
                f'{key}="{_escape_label_value(str(value))}"'
                for key, value in sorted(record.labels.items())
            )
            labels = f"{{{rendered}}}"

        timestamp = (
            f" {record.timestamp_ms}"
            if record.timestamp_ms is not None
            else ""
        )
        return f"{record.name}{labels} {record.value}{timestamp}"

    def render_records(
        self,
        records: list[PrometheusWriteRecord],
    ) -> str:
        return "\n".join(self.render_record(record) for record in records) + "\n"

    def write_records(
        self,
        records: list[PrometheusWriteRecord],
        output_path: Path,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            self.render_records(records),
            encoding="utf_8",
        )
