"""
Verification engine.

Purpose
After config is applied, we must compare observed state to desired state.
This module evaluates a VerificationSpec against observed device state.

Observed state format
observed_state is a dict:
  device name -> dict of model path -> value

Supported check types
path_equals
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datacenter_orchestrator.core.types import VerificationSpec


@dataclass
class VerificationOutcome:
    """
    Verification outcome.

    ok
    True only when every check passes.

    failures
    List of human readable failure messages.

    evidence
    Structured evidence that can be attached to alerts.
    """

    ok: bool
    failures: list[str]
    evidence: dict[str, Any]


def evaluate_verification(
    spec: VerificationSpec,
    observed_state: dict[str, dict[str, Any]],
) -> VerificationOutcome:
    """
    Evaluate a VerificationSpec against observed state.

    We keep this deterministic and strict.
    Unknown check types are treated as failures.
    """

    failures: list[str] = []

    check_results: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {"check_results": check_results}

    for idx, check in enumerate(spec.checks):
        ctype = str(check.get("type", ""))

        if ctype != "path_equals":
            failures.append(f"unsupported check type at index {idx}: {ctype}")
            check_results.append(
                {"index": idx, "type": ctype, "ok": False, "reason": "unsupported"}
            )
            continue

        device = str(check.get("device", ""))
        path = str(check.get("path", ""))
        expected = check.get("expected")

        device_state = observed_state.get(device, {})
        if path not in device_state:
            failures.append(f"missing observed path for device {device}: {path}")
            check_results.append(
                {
                    "index": idx,
                    "type": ctype,
                    "device": device,
                    "path": path,
                    "ok": False,
                    "reason": "missing",
                }
            )
            continue

        observed = device_state.get(path)
        if observed != expected:
            failures.append(
                "value mismatch device "
                f"{device} path {path} expected {expected} observed {observed}"
            )
            check_results.append(
                {
                    "index": idx,
                    "type": ctype,
                    "device": device,
                    "path": path,
                    "ok": False,
                    "expected": expected,
                    "observed": observed,
                }
            )
            continue

        check_results.append(
            {"index": idx, "type": ctype, "device": device, "path": path, "ok": True}
        )

    ok = len(failures) == 0
    return VerificationOutcome(ok=ok, failures=failures, evidence=evidence)
