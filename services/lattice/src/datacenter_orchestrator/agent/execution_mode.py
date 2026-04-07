"""
Execution modes.

apply
Apply the plan using the executor.

simulate
Do not call executor. Instead produce a simulated observed state equal to the
desired values, useful for dry planning.

dry_run
Build plan and report risk, but do not apply.
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionMode(StrEnum):
    apply = "apply"
    simulate = "simulate"
    dry_run = "dry_run"
