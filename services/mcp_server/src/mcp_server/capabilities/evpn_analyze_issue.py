from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


class EVPNAnalyzeIssueError(Exception):
    pass


@dataclass
class EVPNAnalyzeIssueInput:
    question: str
    vendor: str
    scenario: str
    capability: str | None = None
    nos_family: str | None = None
    feature: str | None = None
    device: str | None = None
    fabric: str | None = None
    site: str | None = None
    pod: str | None = None
    vrf: str | None = None
    vni: int | None = None
    mac: str | None = None
    vtep: str | None = None
    incident_id: str | None = None
    timestamp_utc: str | None = None
    limit: int = 5

    @classmethod
    def from_params(cls, data: dict[str, Any]) -> "EVPNAnalyzeIssueInput":
        if not isinstance(data, dict):
            raise EVPNAnalyzeIssueError("params must be an object")

        question = data.get("question")
        vendor = data.get("vendor")
        scenario = data.get("scenario")

        if not isinstance(question, str) or not question.strip():
            raise EVPNAnalyzeIssueError("missing required field question")
        if not isinstance(vendor, str) or not vendor.strip():
            raise EVPNAnalyzeIssueError("missing required field vendor")
        if not isinstance(scenario, str) or not scenario.strip():
            raise EVPNAnalyzeIssueError("missing required field scenario")

        capability = data.get("capability")
        nos_family = data.get("nos_family")
        feature = data.get("feature")
        device = data.get("device")
        fabric = data.get("fabric")
        site = data.get("site")
        pod = data.get("pod")
        vrf = data.get("vrf")
        mac = data.get("mac")
        vtep = data.get("vtep")
        incident_id = data.get("incident_id")
        timestamp_utc = data.get("timestamp_utc")
        vni = data.get("vni")
        limit = data.get("limit", 5)

        if vni is not None and not isinstance(vni, int):
            raise EVPNAnalyzeIssueError("field vni must be an integer when provided")
        if not isinstance(limit, int) or limit <= 0:
            raise EVPNAnalyzeIssueError("field limit must be a positive integer")

        optional_strings = {
            "capability": capability,
            "nos_family": nos_family,
            "feature": feature,
            "device": device,
            "fabric": fabric,
            "site": site,
            "pod": pod,
            "vrf": vrf,
            "mac": mac,
            "vtep": vtep,
            "incident_id": incident_id,
            "timestamp_utc": timestamp_utc,
        }
        for name, value in optional_strings.items():
            if value is not None and not isinstance(value, str):
                raise EVPNAnalyzeIssueError(f"field {name} must be a string when provided")

        return cls(
            question=question.strip(),
            vendor=vendor.strip(),
            scenario=scenario.strip(),
            capability=capability.strip() if isinstance(capability, str) and capability.strip() else None,
            nos_family=nos_family.strip() if isinstance(nos_family, str) and nos_family.strip() else None,
            feature=feature.strip() if isinstance(feature, str) and feature.strip() else None,
            device=device.strip() if isinstance(device, str) and device.strip() else None,
            fabric=fabric.strip() if isinstance(fabric, str) and fabric.strip() else None,
            site=site.strip() if isinstance(site, str) and site.strip() else None,
            pod=pod.strip() if isinstance(pod, str) and pod.strip() else None,
            vrf=vrf.strip() if isinstance(vrf, str) and vrf.strip() else None,
            vni=vni,
            mac=mac.strip() if isinstance(mac, str) and mac.strip() else None,
            vtep=vtep.strip() if isinstance(vtep, str) and vtep.strip() else None,
            incident_id=incident_id.strip() if isinstance(incident_id, str) and incident_id.strip() else None,
            timestamp_utc=timestamp_utc.strip() if isinstance(timestamp_utc, str) and timestamp_utc.strip() else None,
            limit=limit,
        )


class EVPNAnalyzeIssueHandler:
    def __init__(self) -> None:
        self.base_url = os.environ.get("EVPN_ANALYSIS_URL", "http://127.0.0.1:8090").rstrip("/")
        self.timeout_seconds = float(os.environ.get("EVPN_ANALYSIS_TIMEOUT_SECONDS", "30"))

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        params = request.get("params", {})
        parsed = EVPNAnalyzeIssueInput.from_params(params)

        payload = {
            "question": parsed.question,
            "vendor": parsed.vendor,
            "nos_family": parsed.nos_family,
            "scenario": parsed.scenario,
            "capability": parsed.capability,
            "feature": parsed.feature,
            "device": parsed.device,
            "fabric": parsed.fabric,
            "site": parsed.site,
            "pod": parsed.pod,
            "vrf": parsed.vrf,
            "vni": parsed.vni,
            "mac": parsed.mac,
            "vtep": parsed.vtep,
            "incident_id": parsed.incident_id,
            "timestamp_utc": parsed.timestamp_utc,
            "limit": parsed.limit,
        }

        try:
            response = requests.post(
                f"{self.base_url}/evpn/analyze",
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise EVPNAnalyzeIssueError(f"failed to reach EVPN analysis service: {exc}") from exc

        if response.status_code != 200:
            raise EVPNAnalyzeIssueError(
                f"EVPN analysis service returned {response.status_code}: {response.text}"
            )

        body = response.json()
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise EVPNAnalyzeIssueError("EVPN analysis service returned an invalid response")

        return {
            "api_version": "v1",
            "request_id": request.get("request_id", "unknown"),
            "ok": True,
            "result": body.get("result", {}),
        }
