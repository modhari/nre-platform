from __future__ import annotations

from enum import Enum


class Severity(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"
