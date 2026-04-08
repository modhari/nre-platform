from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from gnmi_collection_agent.core.ring import Ring


@dataclass
class BaselinePoint:
    window: Ring

    @property
    def n(self) -> int:
        return self.window.n()

    @property
    def mean(self) -> float:
        return self.window.mean()

    def std(self) -> float:
        return self.window.std()


class BaselineStore:
    def __init__(self, window_size: int = 120) -> None:
        self.window_size = window_size
        self.points: Dict[Tuple[str, str], BaselinePoint] = {}

    def update(self, key: str, metric: str, value: float) -> None:
        k = (key, metric)
        pt = self.points.get(k)
        if pt is None:
            pt = BaselinePoint(window=Ring(self.window_size))
            self.points[k] = pt
        pt.window.push(value)

    def get_point(self, key: str, metric: str) -> BaselinePoint:
        k = (key, metric)
        pt = self.points.get(k)
        if pt is None:
            pt = BaselinePoint(window=Ring(self.window_size))
            self.points[k] = pt
        return pt

    def detect_anomaly(
        self,
        key: str,
        metric: str,
        current_value: float,
        z_threshold: float,
        min_updates: int,
    ) -> Optional[Tuple[float, float, float]]:
        pt = self.get_point(key, metric)
        if pt.n < min_updates:
            return None

        std = pt.std()
        # If the baseline window is flat, std becomes zero.
        # In production, flat baselines do happen, for example quiet metrics or constant rates.
        # We still want to catch spikes, so we apply a small floor to std.
        if std <= 1e-9:
            mean_abs = abs(pt.mean)
            std = max(1.0, mean_abs * 0.05)

        z = (current_value - pt.mean) / std
        if abs(z) >= z_threshold:
            return (pt.mean, std, z)

        return None
