from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class Ring:
    capacity: int
    values: List[float]

    def __init__(self, capacity: int) -> None:
        if capacity <= 1:
            raise ValueError("capacity must be greater than 1")
        self.capacity = capacity
        self.values = []

    def push(self, v: float) -> None:
        self.values.append(v)
        if len(self.values) > self.capacity:
            self.values.pop(0)

    def n(self) -> int:
        return len(self.values)

    def mean(self) -> float:
        if not self.values:
            return 0.0
        return sum(self.values) / float(len(self.values))

    def var(self) -> float:
        if len(self.values) < 2:
            return 0.0
        m = self.mean()
        return sum((x - m) * (x - m) for x in self.values) / float(len(self.values) - 1)

    def std(self) -> float:
        return self.var() ** 0.5
