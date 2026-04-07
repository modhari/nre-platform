from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Send a JSON POST request and decode the JSON response.
    """
    body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def assert_case(case: dict[str, Any], response: dict[str, Any]) -> list[str]:
    """
    Validate one case response and return a list of error messages.

    We keep validation readable and explicit so operators can easily understand why a
    case failed.
    """
    errors: list[str] = []

    if response.get("status") != "ok":
        errors.append(f"expected status ok, got {response.get('status')}")
        return errors

    diagnosis = response.get("diagnosis", {})
    validation_summary = diagnosis.get("validation_summary", {})
    diagnosis_counts = diagnosis.get("diagnosis_counts", {})
    expected = case.get("expected", {})

    expected_grouped = expected.get("has_grouped_alert")
    actual_grouped = validation_summary.get("has_grouped_alert")
    if actual_grouped != expected_grouped:
        errors.append(
            f"expected has_grouped_alert={expected_grouped}, got {actual_grouped}"
        )

    expected_top = expected.get("top_finding_type")
    actual_top = validation_summary.get("top_finding_type")
    if actual_top != expected_top:
        errors.append(
            f"expected top_finding_type={expected_top}, got {actual_top}"
        )

    for finding_type in expected.get("required_findings", []):
        if diagnosis_counts.get(finding_type, 0) <= 0:
            errors.append(
                f"expected finding_type {finding_type} to be present in diagnosis_counts"
            )

    return errors


def main() -> int:
    """
    Run all smoke test cases against the lattice BGP diagnostics endpoint.

    Usage:
    python lattice/examples/bgp_diagnostics_smoke_test.py http://localhost:8081
    """
    if len(sys.argv) != 2:
        print(
            "usage: python lattice/examples/bgp_diagnostics_smoke_test.py "
            "http://localhost:8081"
        )
        return 1

    base_url = sys.argv[1].rstrip("/")
    diagnostics_url = f"{base_url}/diagnostics/bgp"

    cases_path = Path(__file__).with_name("bgp_diagnostics_cases.json")
    cases_data = json.loads(cases_path.read_text())
    cases = cases_data.get("cases", [])

    total = 0
    failed = 0

    for case in cases:
        total += 1
        case_name = case.get("name", "unknown_case")

        try:
            response = post_json(diagnostics_url, case["request"])
            errors = assert_case(case, response)
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {case_name}")
            print(f"  request execution failed: {exc}")
            continue

        if errors:
            failed += 1
            print(f"[FAIL] {case_name}")
            for error in errors:
                print(f"  {error}")
            continue

        diagnosis = response.get("diagnosis", {})
        validation_summary = diagnosis.get("validation_summary", {})
        print(f"[PASS] {case_name}")
        print(
            "  "
            f"finding_count={validation_summary.get('finding_count')} "
            f"highest_severity={validation_summary.get('highest_severity')} "
            f"grouped={validation_summary.get('has_grouped_alert')}"
        )

    print("")
    print(f"completed {total} cases, failed {failed}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
