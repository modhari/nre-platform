from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from gnmi_collection_agent.core.baseline import BaselineStore
from gnmi_collection_agent.core.severity import Severity
from gnmi_collection_agent.core.time import now_unix_s


@dataclass(frozen=True)
class Alert:
    ts_unix_s: float
    alert_name: str
    severity: Severity
    summary: str
    labels: Dict[str, str]
    evidence: Dict[str, Any]
    dedup_key: str


@dataclass
class AlertEngine:
    baseline: BaselineStore

    def anomaly_alert(
        self,
        key: str,
        metric: str,
        value: float,
        z_threshold: float,
        min_updates: int,
        labels: Dict[str, str],
        alert_name: str,
        severity: Severity,
    ) -> Optional[Alert]:
        res = self.baseline.detect_anomaly(
            key=key,
            metric=metric,
            current_value=value,
            z_threshold=z_threshold,
            min_updates=min_updates,
        )
        if res is None:
            return None

        mean, std, z = res
        evidence: Dict[str, Any] = {"metric": metric, "value": value, "mean": mean, "std": std, "z": z}
        dedup_key = f"{key}:{alert_name}:{metric}"
        return Alert(
            ts_unix_s=now_unix_s(),
            alert_name=alert_name,
            severity=severity,
            summary=f"Anomaly detected for {metric}",
            labels=dict(labels),
            evidence=evidence,
            dedup_key=dedup_key,
        )
